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
    stream.write(json.dumps({'name':name,'args':args,'cwd':os.getcwd(),
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
if name == 'Unity': hold(os.environ.get('MOCK_UNITY_DELAY','.3'), os.environ.get('MOCK_UNITY_STATUS','0'))
if name == 'launch_autoware_carla.sh':
    if '--dry-run' in args: sys.exit(int(os.environ.get('MOCK_AUTO_PREFLIGHT','0')))
    def done(*_):
        time.sleep(float(os.environ.get('MOCK_CLEANUP_DELAY','0'))); (root/'delegate-cleanup').touch(); sys.exit(0)
    signal.signal(signal.SIGINT, done); signal.signal(signal.SIGTERM, done)
    hold(os.environ.get('MOCK_AUTO_DELAY','30'), os.environ.get('MOCK_AUTO_STATUS','0'))
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
                  'UB-MR/run_ub_mr.sh', 'UB-MR/download_unity_player.sh', 'launch/launch_autoware_carla.sh'):
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
            self.assertTrue(all(x['name']=='launch_autoware_carla.sh' or x['args']==['compose','version'] for x in e),e)
            self.assertFalse((self.root/'ros-sourced').exists())
            self.assertFalse((self.root/'Client-Logs').exists())
            self.assertEqual(mode,p.stat().st_mode)

    def test_editor_is_independent_and_arguments_and_logs_preserved(self):
        shutil.rmtree(self.root/'CARLA')
        for tool in ('docker','curl','gcloud','ssh'): (self.root/'bin'/tool).unlink()
        r,e=self.run_launcher('--dev','--','-batchmode','a b'); self.assert_ok(r)
        unity=next(x for x in e if x['name']=='Unity')
        self.assertEqual(unity['args'],['-projectPath', str(self.root/'UB-MR'), '-logFile',str(self.root/'Client-Logs/ub-mr/unity-editor.log'),'-batchmode','a b'])
        self.assertEqual(unity['env']['ROS_DOMAIN_ID'],'0')
        self.assertEqual(unity['env']['UB_EXPERIMENT_DIR'],str(self.root/'Client-Logs/ub-mr/experiments'))
        for arguments in (('-logFile','custom log'),('-logFile=custom log',)):
            r,e=self.run_launcher(*arguments,wrapper=True,UB_EXPERIMENT_HOST_DIR='/custom'); self.assert_ok(r)
            unity=next(x for x in e if x['name']=='Unity')
            self.assertEqual(unity['args'][2:],list(arguments))
            self.assertEqual(unity['env']['UB_EXPERIMENT_DIR'],'/custom')

    def test_carla_only_and_localization_ownership(self):
        (self.root/'launch/launch_autoware_carla.sh').unlink()
        r,e=self.run_launcher('--carla',UB_CARLA_EXTRA_SERVICES='redis redis'); self.assert_ok(r)
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
