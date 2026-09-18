import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

MODULE = Path(__file__).resolve().parents[1] / 'install_ub_carla.py'
spec = importlib.util.spec_from_file_location('installer', MODULE)
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)


def archive_bytes(prefix='LinuxNoEditor/'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as bundle:
        for name in installer.CARLA_FILES + ('PythonAPI/carla/dist/carla-0.9.16-cp310-cp310-linux_x86_64.whl',):
            bundle.writestr(prefix + name, b'fixture')
    return output.getvalue()


class FakeDrive:
    def __init__(self):
        self.archive = archive_bytes()
        self.build = installer.DriveFile('build', 'UB-CARLA-v1.1.0.zip', 'application/zip')
        self.folder = installer.DriveFile('maps', 'v1.1.0', installer.FOLDER_MIME)
        self.maps = [installer.DriveFile(name, name, 'application/octet-stream') for name in installer.MAP_FILES]
        self.downloads = []
        self.fail = None

    def list_folder(self, folder):
        return {installer.CARLA_FOLDER: [self.build], installer.MAPS_FOLDER: [self.folder], 'maps': self.maps}[folder]

    def download(self, item, destination):
        self.downloads.append(item.name)
        if item.name == self.fail:
            raise installer.InstallError('simulated interrupted download')
        destination.write_bytes(self.archive if item.id == 'build' else b'fixture')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'CARLA/Builds/v1.1.0'
        self.maps = self.root / 'Autoware/host_data/maps/ub_autonomous_proving_grounds/v1.1.0'
        self.drive = FakeDrive()
        self.stdout = patch('sys.stdout', new_callable=io.StringIO)
        self.stdout.start()
        self.addCleanup(self.stdout.stop)

    def install(self, **kwargs):
        installer.install('v1.1.0', root=self.root, drive=self.drive, **kwargs)

    def test_install_pair_and_skip_on_rerun(self):
        self.install()
        self.assertTrue(installer.is_complete(self.build, installer.CARLA_FILES))
        self.assertTrue(installer.is_complete(self.maps, installer.MAP_FILES))
        self.assertTrue((self.build / 'CarlaUE4.sh').stat().st_mode & stat.S_IXUSR)
        self.assertFalse((self.build / 'LinuxNoEditor').exists())
        self.assertEqual(len(self.drive.downloads), 4)
        with patch.object(self.drive, 'list_folder', side_effect=AssertionError('Unexpected network access')):
            self.install()
        self.assertEqual(len(self.drive.downloads), 4)

    def test_empty_map_placeholder_is_supported(self):
        self.maps.mkdir(parents=True)
        self.install()
        self.assertTrue(installer.is_complete(self.maps, installer.MAP_FILES))

    def test_missing_pcd_prevents_all_downloads(self):
        self.drive.maps = [item for item in self.drive.maps if item.name != 'pointcloud_map.pcd']
        with self.assertRaisesRegex(installer.InstallError, 'pointcloud_map.pcd'):
            self.install()
        self.assertEqual(self.drive.downloads, [])
        self.assertFalse(self.build.exists())

    def test_missing_build_does_not_select_older_release(self):
        self.drive.build = installer.DriveFile('old', 'UB-CARLA-v1.0.0.zip', 'application/zip')
        with self.assertRaisesRegex(installer.InstallError, 'CARLA v1.1.0 not found'):
            self.install()
        self.assertEqual(self.drive.downloads, [])

    def test_existing_build_still_installs_missing_maps(self):
        self.install()
        import shutil
        shutil.rmtree(self.maps)
        self.drive.downloads.clear()
        self.install()
        self.assertEqual(set(self.drive.downloads), set(installer.MAP_FILES))

    def test_maps_only_does_not_require_build_upload(self):
        self.drive.build = installer.DriveFile('old', 'UB-CARLA-v1.0.0.zip', 'application/zip')
        self.install(maps_only=True)
        self.assertFalse(self.build.exists())
        self.assertTrue(installer.is_complete(self.maps, installer.MAP_FILES))

    def test_partial_install_is_preserved(self):
        self.maps.mkdir(parents=True)
        p = self.maps / 'lanelet2_map.osm'
        p.write_text('user map')
        with self.assertRaisesRegex(installer.InstallError, 'Incomplete installation already exists'):
            self.install()
        self.assertEqual(p.read_text(), 'user map')
        self.assertEqual(self.drive.downloads, [])

    def test_failed_map_download_leaves_no_build_install(self):
        self.drive.fail = 'pointcloud_map.pcd'
        with self.assertRaisesRegex(installer.InstallError, 'interrupted'):
            self.install()
        self.assertFalse(self.build.exists())
        self.assertFalse(self.maps.exists())
        self.assertEqual(list(self.build.parent.iterdir()), [])
        self.assertEqual(list(self.maps.parent.iterdir()), [])

    def test_check_does_not_create_directories_or_download(self):
        self.install(check=True)
        self.assertEqual(self.drive.downloads, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_check_ignores_partial_local_install(self):
        self.maps.mkdir(parents=True)
        (self.maps / 'lanelet2_map.osm').write_text('user map')
        self.install(check=True)
        self.assertEqual(self.drive.downloads, [])
        self.assertEqual((self.maps / 'lanelet2_map.osm').read_text(), 'user map')

    def test_flat_build_archive(self):
        self.drive.archive = archive_bytes('')
        self.install()
        self.assertTrue(installer.is_complete(self.build, installer.CARLA_FILES))

    def test_unsafe_archive_rejected(self):
        for name in ['../outside', '/absolute', 'dir\\outside']:
            with self.subTest(name=name):
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w') as bundle:
                    bundle.writestr(name, b'bad')
                self.drive.archive = output.getvalue()
                with self.assertRaisesRegex(installer.InstallError, 'Unsafe archive path'):
                    self.install()
                self.assertFalse(self.build.exists())

    def test_invalid_zip_does_not_install(self):
        self.drive.archive = b'<html>upload incomplete</html>'
        with self.assertRaises(zipfile.BadZipFile):
            self.install()
        self.assertFalse(self.build.exists())

    def test_shared_library_symlinks_are_preserved(self):
        output = io.BytesIO(archive_bytes())
        with zipfile.ZipFile(output, 'a') as bundle:
            bundle.writestr('LinuxNoEditor/libsqlite3.so.0.8.6', b'library')
            link = zipfile.ZipInfo('LinuxNoEditor/libsqlite3.so')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(link, 'libsqlite3.so.0.8.6')
        self.drive.archive = output.getvalue()
        self.install()
        self.assertTrue((self.build / 'libsqlite3.so').is_symlink())
        self.assertEqual((self.build / 'libsqlite3.so').read_bytes(), b'library')

    def test_escaping_symlink_is_rejected(self):
        output = io.BytesIO(archive_bytes())
        with zipfile.ZipFile(output, 'a') as bundle:
            link = zipfile.ZipInfo('LinuxNoEditor/link')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(link, '../../outside')
        self.drive.archive = output.getvalue()
        with self.assertRaisesRegex(installer.InstallError, 'Unsafe archive symlink'):
            self.install()

    def test_archive_missing_required_payload_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as bundle:
            bundle.writestr('readme.txt', 'not a build')
        self.drive.archive = output.getvalue()
        with self.assertRaisesRegex(installer.InstallError, 'exactly one packaged CARLA'):
            self.install()

    def test_duplicate_version_is_rejected(self):
        with self.assertRaisesRegex(installer.InstallError, 'Multiple matches'):
            installer.unique_match([self.drive.build, self.drive.build], ('UB-CARLA-v1.1.0.zip',), 'build')

    def test_versions(self):
        self.assertEqual(installer.normalize_version('1.1.0'), 'v1.1.0')
        self.assertEqual(installer.normalize_version('v1.0.0'), 'v1.0.0')
        for invalid in ['latest', '../v1.1.0', 'v1.1.0/extra', '1.1', '']:
            with self.assertRaises(installer.argparse.ArgumentTypeError):
                installer.normalize_version(invalid)

    def test_public_folder_parser(self):
        row = ['id', ['parent'], 'v1.1.0', installer.FOLDER_MIME] + [None] * 10
        payload = json.dumps([[row], 1])
        escaped = ''.join(f'\\x{ord(c):02x}' for c in payload)
        page = "window['_DRIVE_ivd'] = '" + escaped + "';"
        self.assertEqual(installer.parse_folder(page), [installer.DriveFile('id', 'v1.1.0', installer.FOLDER_MIME)])
        with self.assertRaises(installer.InstallError):
            installer.parse_folder('<html>Please sign in</html>')

    def test_download_confirmation_form(self):
        form = installer.ConfirmationForm()
        form.feed('<form id="download-form" action="https://drive.usercontent.google.com/download">'
                  '<input name="id" value="file"><input value="t" name="confirm"></form>')
        self.assertEqual(form.url(), 'https://drive.usercontent.google.com/download?id=file&confirm=t')
        with self.assertRaises(installer.InstallError):
            installer.ConfirmationForm().url()

    def test_download_size_validation(self):
        response = io.BytesIO(b'short')
        response.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': '10'}
        drive = installer.PublicDrive()
        with patch.object(drive, 'open', return_value=response):
            with self.assertRaisesRegex(installer.InstallError, 'Incomplete download'):
                drive.download(installer.DriveFile('id', 'file', 'application/octet-stream', 10), self.root / 'download')


if __name__ == '__main__':
    unittest.main()
