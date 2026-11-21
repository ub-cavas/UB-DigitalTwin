"""Unified launcher orchestration, tested without Docker, Unity, ROS or network."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = r'''
import json, os, signal, sys, time
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ['MOCK_ROOT'])
with open(root/'events', 'a') as stream:
    stream.write(json.dumps({'name':name,'args':args,'cwd':os.getcwd(),'pid':os.getpid(),
        'env':{k:v for k,v in os.environ.items() if k.startswith(('UB_', 'ROS_', 'BUILD_', 'CARLA_'))}})+'\n')
def hold(delay, code=0):
    time.sleep(float(delay)); sys.exit(int(code))
if name == 'curl':
    print(os.environ.get('MOCK_METADATA', '{"tag_name":"v1.2.3"}'))
    sys.exit(int(os.environ.get('MOCK_CURL_STATUS','0')))
if name == 'download_unity_player.sh':
    tag = os.environ.get('MOCK_DOWNLOAD_TAG', args[0])
    p = root/'UB-MR'/'Builds'/tag/'UB-MR.x86_64'
    p.parent.mkdir(parents=True, exist_ok=True); p.touch()
    sys.exit(int(os.environ.get('MOCK_DOWNLOAD_STATUS','0')))
if name == 'gcloud': sys.exit(int(os.environ.get('MOCK_GCLOUD_STATUS', '0')))
if name == 'ssh':
    if args[args.index('-O')+1] == 'check': sys.exit(int(os.environ.get('MOCK_SSH_CHECK_STATUS','0')))
    sys.exit(0)
if name == 'Unity' and os.environ.pop('MOCK_UNITY_WORKER', None):
    import subprocess; subprocess.Popen([sys.executable, sys.argv[0], *args])  # AssetImportWorker-like child
if name in ('UnityShaderCompiler', 'unityhub-bin'): hold(30)
if name == 'Unity': hold(os.environ.get('MOCK_UNITY_DELAY','.3'), os.environ.get('MOCK_UNITY_STATUS','0'))
if name == 'launch_autoware_carla.sh':
    if '--dry-run' in args: sys.exit(int(os.environ.get('MOCK_AUTO_PREFLIGHT','0')))
    def done(*_):
        time.sleep(float(os.environ.get('MOCK_CLEANUP_DELAY','0'))); (root/'delegate-cleanup').touch(); sys.exit(0)
    signal.signal(signal.SIGINT, done); signal.signal(signal.SIGTERM, done)
    hold(os.environ.get('MOCK_AUTO_DELAY','30'), os.environ.get('MOCK_AUTO_STATUS','0'))
if name == 'launch_mr_pkg_dev.sh':
    if '--dry-run' in args: sys.exit(int(os.environ.get('MOCK_LOC_PREFLIGHT','0')))
    def stopped(*_): (root/'localization-stopped').touch(); sys.exit(0)
    signal.signal(signal.SIGINT, stopped); signal.signal(signal.SIGTERM, stopped)
    hold(os.environ.get('MOCK_LOC_DELAY','30'), os.environ.get('MOCK_LOC_STATUS','0'))
if name == 'run_ub_mr.sh':
    def proxy(sig, _):
        (root/'proxied-signal').touch()
        (root/'running').unlink(missing_ok=True)
        sys.exit(128+sig)
    signal.signal(signal.SIGTERM, proxy); signal.signal(signal.SIGINT, proxy)
    if os.environ.get('MOCK_RUNTIME_EARLY'): sys.exit(int(os.environ['MOCK_RUNTIME_EARLY']))
    if not os.environ.get('MOCK_NO_READY'): (root/'running').touch()
    hold(os.environ.get('MOCK_PLAYER_DELAY','.5'), os.environ.get('MOCK_PLAYER_STATUS','0'))
if name == 'docker':
    if args[0] == 'ps':
        if (root/'running').exists() or ('-a' in args and (root/'stopped').exists()): print('ub-mr-container')
    elif args[0] == 'wait':
        time.sleep(float(os.environ.get('MOCK_PLAYER_DELAY','.5'))); print(os.environ.get('MOCK_PLAYER_STATUS','0'))
    elif args[0] == 'rm': (root/'running').unlink(missing_ok=True)
    elif args[0] == 'inspect':
        if '.Mounts' in args[2]: print(os.environ.get('MOCK_MOUNT',str(root/'UB-MR/Builds/test')))
        elif '.State.Status' in args[2]: print(os.environ.get('MOCK_MAP_STATE','exited 0'))
        else:
            extra_dead = args[-1] == 'redis-id' and os.environ.get('MOCK_EXTRA_FAILURE') == 'stopped' and int((root/'extra-checks').read_text()) >= 3
            print('false' if os.environ.get('MOCK_CARLA_DEAD') or extra_dead else 'true')
    elif args[0] == 'compose':
        cmd = args[1]
        if cmd == 'ps':
            service = args[-1]
            existing = os.environ.get('MOCK_EXISTING_SERVICES','').split()
            if service == 'redis' and os.environ.get('MOCK_EXTRA_FAILURE'):
                counter = root/'extra-checks'
                checks = int(counter.read_text())+1 if counter.exists() else 1
                counter.write_text(str(checks))
                if checks >= 3 and os.environ['MOCK_EXTRA_FAILURE'] == 'disappeared': sys.exit(0)
            if '--status' not in args or service in existing: print(service+'-id')
        if cmd == 'up': hold(os.environ.get('MOCK_COMPOSE_DELAY','0'),os.environ.get('MOCK_COMPOSE_STATUS','0'))
sys.exit(0)
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ub mr ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for d in ('launch/lib', 'UB-MR/Builds/test', 'UB-MR/Scripts',
                  'UB-MR/ProjectSettings', 'CARLA/Builds/v1.1.0', 'bin'):
            (self.root/d).mkdir(parents=True)
        (self.root/'ros-setup').touch()
        for f in ('launch/launch_ub_mr.sh', 'launch/launch_ub_mr_dev.sh', 'launch/launch_autoware_carla_ub_mr_lidar.sh', 'launch/lib/iap_tunnel.sh'):
            target = self.root/f
            target.write_text((ROOT/f).read_text().replace('/opt/ros/humble/setup.bash', str(self.root/'ros-setup')).replace('{1..600}', '{1..10}'))
            target.chmod(0o755)
        for f in ('bin/docker', 'bin/curl', 'bin/Unity', 'bin/gcloud', 'bin/ssh', 'bin/xhost',
                  'UB-MR/run_ub_mr.sh', 'UB-MR/download_unity_player.sh', 'launch/launch_autoware_carla.sh',
                  'launch/launch_mr_pkg_dev.sh'):
            target = self.root/f
            target.write_text('#!'+sys.executable+'\n'+COMMAND); target.chmod(0o755)
        self.player('test')
        (self.root/'UB-MR/ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: test\n')
        (self.root/'UB-MR/Scripts/host_ros2_env.bash').write_text('touch "${MOCK_ROOT}/ros-sourced"\n')
        (self.root/'CARLA/docker-compose.yml').touch()
        (self.root/'CARLA/Builds/v1.1.0/CarlaUE4.sh').touch()
        self.env = {k:v for k,v in os.environ.items()
                    if not k.startswith(('UB_', 'MOCK_', 'UNITY_', 'AUTOWARE_', 'BUILD_', 'CARLA_', 'IMAGE_'))}
        self.env.update(PATH=f'{self.root/"bin"}:{os.environ["PATH"]}', MOCK_ROOT=str(self.root),
                        UB_MR_BUILD_FOLDER='test', UNITY_EDITOR=str(self.root/'bin/Unity'))

    def player(self, tag):
        p = self.root/'UB-MR/Builds'/tag/'UB-MR.x86_64'
        p.parent.mkdir(parents=True, exist_ok=True); p.touch()
        return p

    def events(self):
        f = self.root/'events'
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def run_launcher(self, *args, wrapper=False, **env):
        (self.root/'events').unlink(missing_ok=True)
        result = subprocess.run(['bash', str(self.root/'launch'/('launch_ub_mr_dev.sh' if wrapper else 'launch_ub_mr.sh')), *args],
                                env={**self.env, **env}, text=True, capture_output=True, timeout=15)
        return result, self.events()

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def wait_event(self, name, timeout=5, args=None):
        # A detached editor may record its event after the launcher has exited.
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            for event in self.events():
                if event['name'] == name and (args is None or args(event['args'])): return event
            time.sleep(.02)
        self.fail(f'{name} event was never recorded: {self.events()}')

    @staticmethod
    def alive(pid):
        try: os.kill(pid, 0)
        except ProcessLookupError: return False
        return True

    def kill_editors(self):
        # Detached mock editors outlive the launcher; never touches other processes.
        for event in self.events():
            if event['name'] == 'Unity' and event['pid'] not in self.editor_pids: self.editor_pids.append(event['pid'])
        for pid in self.editor_pids:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
        for pid in self.editor_pids:
            deadline = time.monotonic()+5
            while self.alive(pid) and time.monotonic() < deadline: time.sleep(.02)

    def track_editors(self):
        self.editor_pids = []
        self.addCleanup(self.kill_editors)

    def fake_editor(self, *project_args, cwd=None, name='Unity', count=1, **env):
        # Starts a mock editor (or other process) for the launcher to see; the test
        # owns it and every PID it records, all killed in cleanup.
        exe = self.root/'bin'/name
        if not exe.exists(): shutil.copy(self.root/'bin/Unity', exe)
        p = subprocess.Popen([sys.executable, str(exe), *project_args], cwd=cwd,
                             env={**self.env, 'MOCK_UNITY_DELAY':'30', **env}, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            if p.poll() is None: p.kill()
            p.wait()
        self.addCleanup(stop)
        deadline = time.monotonic()+5
        while True:
            seen = [x for x in self.events() if x['name'] == name and x['args'] == list(project_args)]
            if len(seen) >= count: break
            if time.monotonic() > deadline: self.fail(f'{name} mock never started: {self.events()}')
            time.sleep(.02)
        for x in seen:
            if x['pid'] not in self.editor_pids: self.editor_pids.append(x['pid'])
        (self.root/'events').unlink(missing_ok=True)
        return p

    def popen_launcher(self, *args, **env):
        (self.root/'events').unlink(missing_ok=True)
        p = subprocess.Popen(['bash', str(self.root/'launch/launch_ub_mr.sh'), *args], env={**self.env, **env},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        def stop():
            if p.poll() is None: p.kill(); p.communicate()
        self.addCleanup(stop)
        return p

    def test_cli_rejects_invalid_arguments_without_actions(self):
        for args in (('--version',), ('--version',''), ('--version','../bad'), ('--version','-bad'),
                     ('--dev','--version','test'), ('--injection',), ('--injection',''),
                     ('--auto','--injection','invalid'), ('--injection','both'), ('--carla','--injection','boxes'), ('--unknown',), ('--','-batchmode')):
            with self.subTest(args=args):
                r,e = self.run_launcher(*args); self.assertEqual(r.returncode,2); self.assertEqual(e,[])
        r,e = self.run_launcher('--help'); self.assert_ok(r); self.assertEqual(e,[])

    def test_standalone_cached_player_without_optional_trees(self):
        shutil.rmtree(self.root/'CARLA')
        (self.root/'launch/launch_autoware_carla.sh').unlink()
        shutil.rmtree(self.root/'UB-MR/Scripts'); shutil.rmtree(self.root/'UB-MR/ProjectSettings')
        for tool in ('Unity','curl','gcloud','ssh'): (self.root/'bin'/tool).unlink()
        r,e = self.run_launcher(); self.assert_ok(r)
        runtime = next(x for x in e if x['name']=='run_ub_mr.sh')
        self.assertEqual(runtime['args'],['test','/app/ub-mr.sh'])
        self.assertEqual(runtime['cwd'], str(self.root/'UB-MR'))
        execs=[x['args'] for x in e if x['name']=='docker' and x['args'][0]=='exec']
        self.assertEqual(execs[0][:4],['exec','-d','ub-mr-container','bash'])
        self.assertEqual(execs[0][-2:],['bash','autoware_localization'])
        self.assertEqual(execs[1][-2:],['bash','autoware_localization'])
        r,e = self.run_launcher(UB_MR_LOCALIZATION='0'); self.assert_ok(r)
        self.assertFalse(any(x['args'][0]=='exec' for x in e if x['name']=='docker'))

    def test_precedence_and_aliases(self):
        for args, env, tag in [
            (('--version','v1.2.3'), {'UB_MR_BUILD_FOLDER':'wrong','UB_MR_RELEASE':'wrong'}, '1.2.3'),
            ((), {'UB_MR_BUILD_FOLDER':'test','UB_MR_RELEASE':'wrong'}, 'test'),
            ((), {'UB_MR_BUILD_FOLDER':'','UB_MR_RELEASE':'v2.0'}, '2.0'),
        ]:
            self.player(tag)
            r,e = self.run_launcher(*args, **env); self.assert_ok(r)
            self.assertEqual(next(x for x in e if x['name']=='run_ub_mr.sh')['args'][0],tag)
            self.assertFalse(any(x['name']=='curl' for x in e))
        self.player('v1.2.3')
        r,e=self.run_launcher('--version','v1.2.3'); self.assert_ok(r)
        self.assertEqual(next(x for x in e if x['name']=='run_ub_mr.sh')['args'][0],'v1.2.3')

    def test_latest_resolves_once_and_uses_only_matching_cache(self):
        self.player('1.2.3'); self.player('unrelated')
        r,e = self.run_launcher(UB_MR_BUILD_FOLDER=''); self.assert_ok(r)
        self.assertEqual(len([x for x in e if x['name']=='curl']),1)
        self.assertFalse(any(x['name']=='download_unity_player.sh' for x in e))
        shutil.rmtree(self.root/'UB-MR/Builds/1.2.3')
        r,e = self.run_launcher(UB_MR_BUILD_FOLDER=''); self.assert_ok(r)
        download = next(x for x in e if x['name']=='download_unity_player.sh')
        self.assertEqual(download['args'],['v1.2.3']); self.assertEqual(download['cwd'],str(self.root/'UB-MR'))

    def test_release_failures_prevent_clients_and_tunnels(self):
        for env in ({'MOCK_METADATA':'garbage'}, {'MOCK_METADATA':'{"tag_name":"../bad"}'},
                    {'MOCK_CURL_STATUS':'22'}, {'MOCK_DOWNLOAD_TAG':'other'}, {'MOCK_DOWNLOAD_STATUS':'19'}):
            with self.subTest(env=env):
                shutil.rmtree(self.root/'UB-MR/Builds/v1.2.3',ignore_errors=True)
                r,e = self.run_launcher('--iap', UB_MR_BUILD_FOLDER='', **env)
                self.assertNotEqual(r.returncode,0)
                self.assertFalse(any(x['name'] in ('gcloud','run_ub_mr.sh') for x in e))

    def test_dry_run_does_not_mutate_or_resolve(self):
        p=self.root/'UB-MR/Builds/test/UB-MR.x86_64'; mode=p.stat().st_mode
        for args,env in [(('--iap','--dry-run'),{'UB_MR_BUILD_FOLDER':''}),
                         (('--version','absent','--dry-run'),{}),
                         (('--dev','--carla','--dry-run'),{}),
                         (('--dev','--auto','--dry-run'),{})]:
            r,e=self.run_launcher(*args, **env); self.assert_ok(r)
            self.assertTrue(all(x['name']=='launch_autoware_carla.sh' or x['args']==['compose','version']
                                or (x['name']=='launch_mr_pkg_dev.sh' and '--dry-run' in x['args']) for x in e),e)
            self.assertFalse((self.root/'ros-sourced').exists())
            self.assertFalse((self.root/'Client-Logs').exists())
            self.assertEqual(mode,p.stat().st_mode)

    def test_editor_is_independent_and_arguments_and_logs_preserved(self):
        self.track_editors()
        shutil.rmtree(self.root/'CARLA')
        for tool in ('docker','curl','gcloud','ssh'): (self.root/'bin'/tool).unlink()
        r,e=self.run_launcher('--dev','--','-batchmode','a b',UB_MR_LOCALIZATION='0'); self.assert_ok(r)
        unity=self.wait_event('Unity')
        self.assertEqual(unity['args'],['-projectPath', str(self.root/'UB-MR'), '-logFile',str(self.root/'Client-Logs/ub-mr/unity-editor.log'),'-batchmode','a b'])
        self.assertEqual(unity['env']['ROS_DOMAIN_ID'],'0')
        self.assertEqual(unity['env']['UB_EXPERIMENT_DIR'],str(self.root/'Client-Logs/ub-mr/experiments'))
        for arguments in (('-logFile','custom log'),('-logFile=custom log',)):
            self.kill_editors()
            r,e=self.run_launcher(*arguments,wrapper=True,UB_EXPERIMENT_HOST_DIR='/custom',UB_MR_LOCALIZATION='0'); self.assert_ok(r)
            unity=self.wait_event('Unity')
            self.assertEqual(unity['args'][2:],list(arguments))
            self.assertEqual(unity['env']['UB_EXPERIMENT_DIR'],'/custom')

    def test_localization_node_follows_carla_flag(self):
        for args,node in ((('--dry-run',),'autoware_localization'),(('--carla','--dry-run'),'carla_localization'),
                          (('--auto','--dry-run'),'carla_localization')):
            with self.subTest(args=args):
                r,e=self.run_launcher(*args); self.assert_ok(r)
                self.assertIn(f'mr_pkg localization: {node}', r.stdout)
                self.assertIn(f'ros2\\ launch\\ mr_pkg\\ {node}.launch.py', r.stdout)
        self.track_editors()
        for args,expected in ((('--dev',),['--physical']),(('--dev','--carla'),[]),(('--dev','--auto'),[])):
            with self.subTest(args=args):
                self.kill_editors()
                (self.root/'localization-stopped').unlink(missing_ok=True)
                p=self.popen_launcher(*args)
                self.wait_event('launch_mr_pkg_dev.sh', args=lambda a: '--dry-run' not in a)
                os.kill(p.pid,signal.SIGTERM)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,143,out+err)
                e=self.events()
                calls=[x['args'] for x in e if x['name']=='launch_mr_pkg_dev.sh']
                self.assertEqual(calls,[expected+['--dry-run'],expected])
                self.assertTrue((self.root/'localization-stopped').exists())
                self.assertFalse(any(x['name']=='docker' and x['args'][0]=='exec' for x in e))
        self.kill_editors()
        r,e=self.run_launcher('--dev',UB_MR_LOCALIZATION='0'); self.assert_ok(r)
        self.assertFalse(any(x['name']=='launch_mr_pkg_dev.sh' for x in e))

    def test_editor_localization_failures(self):
        self.track_editors()
        r,e=self.run_launcher('--dev','--iap',MOCK_LOC_PREFLIGHT='1')
        self.assertNotEqual(r.returncode,0)
        self.assertFalse(any(x['name'] in ('Unity','gcloud') for x in e))
        r,e=self.run_launcher('--dev','--carla',MOCK_LOC_DELAY='.1',MOCK_LOC_STATUS='5',MOCK_UNITY_DELAY='30')
        self.assertEqual(r.returncode,5,r.stdout+r.stderr)
        self.assertIn('carla_localization exited unexpectedly',r.stderr)
        self.assertTrue(any(x['args'][:2]==['compose','stop'] for x in e))
        self.assertTrue(self.alive(self.wait_event('Unity')['pid']))

    def test_running_editor_is_reused_not_launched(self):
        self.track_editors()
        for project_args,cwd in ((('-projectPath',str(self.root/'UB-MR')),None),
                                 (('-projectpath','UB-MR'),str(self.root))):
            with self.subTest(project_args=project_args):
                fake=self.fake_editor(*project_args,cwd=cwd)
                p=self.popen_launcher('--dev','--iap','--','-batchmode',UB_MR_LOCALIZATION='0')
                self.wait_event('ssh', args=lambda a: 'check' in a)
                time.sleep(.5)
                os.kill(p.pid,signal.SIGTERM)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,143,out+err)
                self.assertFalse(any(x['name']=='Unity' for x in self.events()))
                self.assertIn(f'(PID {fake.pid}); not launching another.',out)
                self.assertIn('-batchmode',err); self.assertIn('-logFile',err)
                self.assertTrue(self.alive(fake.pid))
                self.assertEqual(self.events()[-1]['name'],'ssh')
                fake.kill(); fake.wait()
        fake=self.fake_editor('-projectPath',str(self.root/'UB-MR'))
        start=time.monotonic()
        r,e=self.run_launcher('--dev',UB_MR_LOCALIZATION='0'); self.assert_ok(r)
        self.assertLess(time.monotonic()-start,5)
        self.assertIn(f'(PID {fake.pid}); not launching another.',r.stdout)
        self.assertNotIn('-- (',r.stderr); self.assertIn('-logFile',r.stderr)
        time.sleep(.3)
        self.assertFalse(any(x['name']=='Unity' for x in self.events()))
        self.assertTrue(self.alive(fake.pid))

    def test_editor_detection_edge_cases(self):
        self.track_editors()
        project = self.root/'UB-MR'
        (self.root/'project link').symlink_to(project)
        for label, project_args, cwd, name, reused in (
            ('symlinked project path', ('-projectPath', str(self.root/'project link')), None, 'Unity', True),
            ('equals form', ('-projectPath='+str(project),), None, 'Unity', True),
            ('trailing slash', ('-projectPath', str(project)+'/'), None, 'Unity', True),
            ('relative path after chdir into project', ('-projectPath', 'UB-MR'), str(project), 'Unity', True),
            ('UnityShaderCompiler is not an editor', ('-projectPath', str(project)), None, 'UnityShaderCompiler', False),
            ('unityhub-bin is not an editor', ('-projectPath', str(project)), None, 'unityhub-bin', False),
        ):
            with self.subTest(label):
                fake = self.fake_editor(*project_args, cwd=cwd, name=name)
                r,e = self.run_launcher('--dev','--dry-run'); self.assert_ok(r)
                if reused:
                    self.assertIn(f'would reuse running editor PID {fake.pid}.', r.stdout)
                else:
                    self.assertIn('Unity editor: not running; would launch detached:', r.stdout)
                fake.kill(); fake.wait()

    def test_main_editor_is_reported_instead_of_worker(self):
        self.track_editors()
        project_args = ('-projectPath', str(self.root/'UB-MR'))
        parent = self.fake_editor(*project_args, count=2, MOCK_UNITY_WORKER='1')
        self.assertEqual(len(self.editor_pids), 2)
        r,e = self.run_launcher('--dev','--dry-run'); self.assert_ok(r)
        self.assertIn(f'would reuse running editor PID {parent.pid}.', r.stdout)

    def test_other_project_editor_and_stale_lockfile_do_not_block_launch(self):
        self.track_editors()
        (self.root/'Other').mkdir()
        (self.root/'UB-MR/Temp').mkdir(); (self.root/'UB-MR/Temp/UnityLockfile').touch()
        self.fake_editor('-projectPath',str(self.root/'Other'))
        r,e=self.run_launcher('--dev',UB_MR_LOCALIZATION='0'); self.assert_ok(r)
        unity=self.wait_event('Unity',args=lambda a: a[:2]==['-projectPath',str(self.root/'UB-MR')])
        self.editor_pids.append(unity['pid'])
        self.assertIn('Started Unity editor (detached',r.stdout)

    def test_launched_editor_is_detached_and_survives_signals_with_companions(self):
        self.track_editors()
        for sig,group,code in ((signal.SIGINT,False,130),(signal.SIGTERM,True,143)):
            with self.subTest(sig=sig,group=group):
                self.kill_editors()
                for f in ('localization-stopped',): (self.root/f).unlink(missing_ok=True)
                p=self.popen_launcher('--dev','--carla','--iap',MOCK_UNITY_DELAY='30')
                unity=self.wait_event('Unity')
                self.wait_event('launch_mr_pkg_dev.sh', args=lambda a: '--dry-run' not in a)
                pid=unity['pid']; self.editor_pids.append(pid)
                self.assertEqual(os.getsid(pid),pid)
                self.assertNotEqual(os.getsid(pid),os.getsid(p.pid))
                self.assertEqual(os.readlink(f'/proc/{pid}/fd/0'),'/dev/null')
                console=str(self.root/'Client-Logs/ub-mr/unity-editor-console.log')
                self.assertEqual(os.readlink(f'/proc/{pid}/fd/1'),console)
                self.assertEqual(os.readlink(f'/proc/{pid}/fd/2'),console)
                (os.killpg if group else os.kill)(p.pid,sig)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,code,out+err)
                e=self.events()
                self.assertTrue((self.root/'localization-stopped').exists())
                self.assertTrue(any(x['args'][:2]==['compose','stop'] for x in e))
                self.assertEqual(e[-1]['name'],'ssh')
                self.assertTrue(self.alive(pid))

    def test_editor_exit_does_not_end_session_with_companions(self):
        self.track_editors()
        (self.root/'localization-stopped').unlink(missing_ok=True)
        p=self.popen_launcher('--dev',MOCK_UNITY_DELAY='.1')
        self.wait_event('Unity')
        self.wait_event('launch_mr_pkg_dev.sh', args=lambda a: '--dry-run' not in a)
        time.sleep(1)
        self.assertIsNone(p.poll())
        os.kill(p.pid,signal.SIGTERM)
        out,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,143,out+err)
        self.assertTrue((self.root/'localization-stopped').exists())

    def test_editor_only_session_exits_zero_and_leaves_editor_running(self):
        self.track_editors()
        start=time.monotonic()
        r,e=self.run_launcher('--dev',UB_MR_LOCALIZATION='0',MOCK_UNITY_DELAY='30'); self.assert_ok(r)
        self.assertLess(time.monotonic()-start,5)
        self.assertIn('No companions selected; leaving the Unity editor running and exiting.',r.stdout)
        unity=self.wait_event('Unity')
        self.assertTrue(self.alive(unity['pid']))

    def test_dev_dry_run_reports_editor_reuse_or_launch(self):
        self.track_editors()
        def check(r,e):
            self.assert_ok(r)
            self.assertFalse(any(x['name'] in ('Unity','gcloud','ssh') for x in e),e)
            self.assertFalse((self.root/'Client-Logs').exists())
        r,e=self.run_launcher('--dev','--dry-run'); check(r,e)
        self.assertIn('Unity editor: not running; would launch detached:',r.stdout)
        self.assertIn('-projectPath',r.stdout)
        self.assertIn('console output -> '+str(self.root/'Client-Logs/ub-mr/unity-editor-console.log'),r.stdout)
        fake=self.fake_editor('-projectPath',str(self.root/'UB-MR'))
        r,e=self.run_launcher('--dev','--iap','--dry-run'); check(r,e)
        self.assertIn(f'would reuse running editor PID {fake.pid}',r.stdout)
        self.assertIn('-logFile',r.stderr)
        self.assertNotIn('-projectPath',r.stdout)

    def test_carla_only_and_localization_ownership(self):
        (self.root/'launch/launch_autoware_carla.sh').unlink()
        r,e=self.run_launcher('--carla',UB_CARLA_EXTRA_SERVICES='redis redis',MOCK_PLAYER_DELAY='1.5'); self.assert_ok(r)
        up=next(x for x in e if x['name']=='docker' and x['args'][:2]==['compose','up'])
        self.assertEqual(up['args'][-3:],['carla','map-loader','redis'])
        self.assertEqual(up['cwd'],str(self.root/'CARLA'))
        self.assertEqual(up['env']['BUILD_FOLDER'],'v1.1.0')
        self.assertEqual(len([x for x in e if x['name']=='docker' and x['args'][:2]==['exec','-d']]),1)
        self.assertFalse(any('down' in x['args'] for x in e))
        self.assertTrue(any(x['args'][:2]==['compose','stop'] for x in e))

    def test_existing_services_and_keep_are_preserved(self):
        for env in ({'MOCK_EXISTING_SERVICES':'carla'}, {'UB_KEEP_CARLA':'1'}):
            r,e=self.run_launcher('--carla',**env); self.assert_ok(r)
            stops=[x for x in e if x['args'][:2]==['compose','stop']]
            if 'UB_KEEP_CARLA' in env: self.assertEqual(stops,[])
            else: self.assertNotIn('carla',stops[0]['args'])

    def test_carla_failure_and_partial_start_cleanup(self):
        for env in ({'MOCK_COMPOSE_STATUS':'23'},{'MOCK_MAP_STATE':'exited 7'}, {'MOCK_CARLA_DEAD':'1'}):
            r,e=self.run_launcher('--carla',**env); self.assertNotEqual(r.returncode,0)
            self.assertTrue(any(x['args'][:2]==['compose','stop'] for x in e))
            self.assertTrue(any(x['args'][:2]==['rm','-f'] for x in e))

    def test_auto_delegates_once_and_primary_exit_stops_delegate(self):
        r,e=self.run_launcher('--auto','--carla'); self.assert_ok(r)
        calls=[x for x in e if x['name']=='launch_autoware_carla.sh']
        self.assertEqual([x['args'] for x in calls],[['--dry-run'],[]])
        self.assertTrue((self.root/'delegate-cleanup').exists())
        self.assertFalse(any(x['args'][:2]==['compose','up'] for x in e))

    def test_explicit_injection_delegation_and_defaults(self):
        for mode in ('lidar', 'boxes', 'both'):
            for args in (('--auto','--injection',mode), ('--injection',mode,'--auto','--dev','--dry-run')):
                r,e = self.run_launcher(*args, UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC='/wrong',
                                        UB_MR_PERCEPTION_PROFILE='0', UB_AUTOWARE_EGO_ONLY_PERCEPTION='1')
                self.assert_ok(r)
                calls = [x for x in e if x['name']=='launch_autoware_carla.sh']
                self.assertEqual([x['args'] for x in calls], [['--dry-run']] if '--dry-run' in args else [['--dry-run'],[]])
                for call in calls:
                    env = call['env']
                    self.assertEqual(env['UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC'],
                                     '/sensing/lidar/top/pointcloud_before_sync'+('' if mode=='boxes' else '_modified'))
                    self.assertEqual(env['UB_MR_PERCEPTION_PROFILE'],'1')
                    self.assertEqual(env['UB_AUTOWARE_EGO_ONLY_PERCEPTION'],'0')
                if '--dry-run' in args:
                    self.assertIn('launch_autoware_carla_ub_mr_lidar.sh --injection '+mode, r.stdout)
        r,e = self.run_launcher('--auto','--dry-run', UB_MR_PERCEPTION_PROFILE='0',
                                UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC='/inherited')
        self.assert_ok(r)
        env = next(x['env'] for x in e if x['name']=='launch_autoware_carla.sh')
        self.assertEqual(env['UB_AUTOWARE_EGO_ONLY_PERCEPTION'],'1')
        self.assertEqual(env['UB_AUTOWARE_CARLA_TOP_LIDAR_SOURCE_TOPIC'],'/inherited')

    def test_selected_delegate_failure_and_long_cleanup_with_iap(self):
        r,e = self.run_launcher('--auto','--injection','both','--iap', MOCK_CLEANUP_DELAY='5.5')
        self.assert_ok(r)
        self.assertTrue((self.root/'delegate-cleanup').exists())
        self.assertEqual(e[-1]['name'],'ssh')
        for env,code in (({'MOCK_AUTO_PREFLIGHT':'41'},41),
                         ({'MOCK_AUTO_DELAY':'.1','MOCK_AUTO_STATUS':'37','MOCK_PLAYER_DELAY':'30'},37)):
            r,e = self.run_launcher('--auto','--injection','both','--iap', **env)
            self.assertEqual(r.returncode,code,r.stdout+r.stderr)

    def test_primary_and_companion_errors(self):
        for args,env,code in [((),{'MOCK_PLAYER_STATUS':'29'},29),
                              ((),{'MOCK_RUNTIME_EARLY':'31'},31),
                              (('--auto',),{'MOCK_AUTO_DELAY':'.1','MOCK_AUTO_STATUS':'37','MOCK_PLAYER_DELAY':'30'},37),
                              (('--auto',),{'MOCK_AUTO_DELAY':'.1','MOCK_PLAYER_DELAY':'30'},1),
                              (('--auto',),{'MOCK_AUTO_PREFLIGHT':'41'},41)]:
            r,e=self.run_launcher(*args,**env); self.assertEqual(r.returncode,code,r.stdout+r.stderr)

    def test_reused_container_mount_validation_and_keep_tunnel(self):
        (self.root/'running').touch()
        r,e=self.run_launcher(MOCK_MOUNT='/wrong'); self.assertNotEqual(r.returncode,0)
        self.assertFalse(any(x['args'][:2]==['rm','-f'] for x in e))
        r,e=self.run_launcher('--iap',UB_KEEP_MR='1'); self.assert_ok(r)
        self.assertFalse(any(x['args'][:2]==['rm','-f'] for x in e))
        self.assertEqual(e[-1]['name'],'ssh'); self.assertIn('exit',e[-1]['args'])

    def test_signals_cleanup_primary_and_iap(self):
        for sig,group in ((signal.SIGTERM,False),(signal.SIGINT,False),(signal.SIGTERM,True)):
            (self.root/'events').unlink(missing_ok=True)
            p=subprocess.Popen(['bash',str(self.root/'launch/launch_ub_mr.sh'),'--iap','--auto','--injection','both'],env={**self.env,'MOCK_PLAYER_DELAY':'30'},
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if any(x['name']=='run_ub_mr.sh' for x in self.events()): break
                    time.sleep(.02)
                (os.killpg if group else os.kill)(p.pid,sig)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,128+sig,out+err)
                self.assertTrue(any(x['args'][:2]==['rm','-f'] for x in self.events()))
                self.assertEqual(self.events()[-1]['name'],'ssh')
            finally:
                if p.poll() is None: p.kill(); p.communicate()

    def test_readiness_timeout_and_kept_owned_player(self):
        r,e=self.run_launcher(MOCK_NO_READY='1',MOCK_PLAYER_DELAY='30')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('Timed out',r.stderr)
        self.assertFalse(any(x['args'][:2]==['rm','-f'] for x in e))
        r,e=self.run_launcher('--auto','--iap',UB_KEEP_MR='1')
        self.assert_ok(r)
        self.assertFalse(any(x['args'][:2]==['rm','-f'] for x in e))
        self.assertTrue((self.root/'delegate-cleanup').exists())
        self.assertEqual(e[-1]['name'],'ssh')

    def test_kept_player_cli_never_proxies_termination(self):
        r,e=self.run_launcher('--auto','--iap', UB_KEEP_MR='1',
                              MOCK_PLAYER_DELAY='30',MOCK_AUTO_DELAY='.2',MOCK_AUTO_STATUS='7')
        self.assertEqual(r.returncode,7,r.stdout+r.stderr)
        self.assertFalse((self.root/'proxied-signal').exists())
        self.assertTrue((self.root/'running').exists())
        self.assertFalse(any(x['args'][:2]==['rm','-f'] for x in e))
        self.assertEqual(e[-1]['name'],'ssh')

    def test_stopped_container_is_never_claimed_or_deleted(self):
        (self.root/'stopped').touch()
        r,e=self.run_launcher('--iap')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('stopped container',r.stderr)
        self.assertFalse(any(x['name'] in ('run_ub_mr.sh','gcloud') or x['args'][:2]==['rm','-f'] for x in e))
        self.assertTrue((self.root/'stopped').exists())

    def test_delegate_cleanup_can_take_more_than_five_seconds(self):
        r,e=self.run_launcher('--auto', MOCK_CLEANUP_DELAY='5.5')
        self.assert_ok(r)
        self.assertTrue((self.root/'delegate-cleanup').exists())

    def test_signal_during_compose_startup_cleans_everything(self):
        p=subprocess.Popen(['bash',str(self.root/'launch/launch_ub_mr.sh'),'--carla','--iap'],
                           env={**self.env,'MOCK_PLAYER_DELAY':'30','MOCK_COMPOSE_DELAY':'30'},
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if any(x['args'][:2]==['compose','up'] for x in self.events()): break
                time.sleep(.02)
            else: self.fail('Compose startup was never reached')
            os.kill(p.pid,signal.SIGTERM)
            out,err=p.communicate(timeout=10)
            self.assertEqual(p.returncode,143,out+err)
            self.assertTrue(any(x['args'][:2]==['compose','stop'] for x in self.events()))
            self.assertTrue(any(x['args'][:2]==['rm','-f'] for x in self.events()))
            self.assertEqual(self.events()[-1]['name'],'ssh')
        finally:
            if p.poll() is None: p.kill(); p.communicate()

    def test_extra_service_exit_fails_without_claiming_reused_service(self):
        for failure in ('stopped','disappeared'):
            with self.subTest(failure=failure):
                (self.root/'extra-checks').unlink(missing_ok=True)
                r,e=self.run_launcher('--carla', UB_CARLA_EXTRA_SERVICES='redis',
                                      MOCK_EXISTING_SERVICES='redis',MOCK_EXTRA_FAILURE=failure,
                                      MOCK_PLAYER_DELAY='30')
                self.assertNotEqual(r.returncode,0)
                self.assertIn("companion service 'redis'",r.stderr)
                self.assertGreaterEqual(int((self.root/'extra-checks').read_text()),3)
                stops=[x for x in e if x['args'][:2]==['compose','stop']]
                self.assertEqual(len(stops),1)
                self.assertNotIn('redis',stops[0]['args'])
                self.assertIn('carla',stops[0]['args'])
                self.assertTrue(any(x['args'][:2]==['rm','-f'] for x in e))

    def test_two_machine_caller_keeps_full_stack(self):
        source=(ROOT/'scripts/launch_ub_mr_carla_client.sh').read_text()
        self.assertIn('launch_ub_mr.sh --auto --dry-run',source)
        self.assertIn('launch_ub_mr.sh" --auto --dry-run',source)
        self.assertIn('launch_ub_mr.sh" --auto\n',source)


if __name__ == '__main__': unittest.main()
