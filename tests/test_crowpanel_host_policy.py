"""Compile and run the production bounded host-policy codec and transaction model."""
import os
import json
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed local C++ source and owned test executable

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def host_policy_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no host C++ compiler")
    binary = tmp_path_factory.mktemp("host_policy") / ("test.exe" if os.name == "nt" else "test")
    build = subprocess.run(  # nosec B603 - fixed owned paths, no shell or device access
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
         str(ROOT / "tests/crowpanel_host/ble_host_policy_test.cpp"), "-o", str(binary)],
        text=True, capture_output=True)
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize("scenario", ("codec", "fragments", "ordering", "completion", "generations", "operations", "golden-commands", "durability", "supersession", "handshake", "handshake-reboots", "admission-lost", "link-history", "enroll-timeout", "result-scope", "late-results", "forget"))
def test_production_host_policy(host_policy_binary, scenario):
    run = subprocess.run(  # nosec B603 - locally built executable, fixed scenario argument
        [str(host_policy_binary), scenario], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("kind", ("status", "max_list", "unsupported"))
def test_python_producer_golden_frames(host_policy_binary, kind):
    vectors = json.loads((ROOT / "tests/fixtures/ble_host_policy_v1.json").read_text())
    run = subprocess.run(  # nosec B603 - fixed owned binary; fixture contains inert hex bytes only
        [str(host_policy_binary), "golden-frames", kind, *vectors[kind]["frames_hex"]],
        text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_production_ui_status_prioritizes_current_fault_and_labels_leftover_diagnostics(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no host C++ compiler")
    ui = (ROOT / "firmware/crowpanel-remote/src/ble_host_ui.cpp").read_text()
    status = ui[ui.index("void status_text("):ui.index("bool send_request(")]
    fixture = ROOT / "tests/crowpanel_host/ble_host_policy_test.cpp"
    source = tmp_path / "status.cpp"
    source.write_text('#define main existing_panel_tests\n#include "' + fixture.as_posix() + '"\n#undef main\n'
        'hp::Control g_control(77);\n'
        'void peer_name(const uint8_t *id,uint32_t,char *out,size_t capacity) { snprintf(out,capacity,"host-%u",id[7]); }\n'
        + status + r'''
int main() {
    uint8_t body[278], frame[64]; char text[256]; seed(g_control);
    assert(g_control.begin(hp::DISCONNECT,6,frame,sizeof(frame)));
    const uint32_t request=ble_status::read32(frame+12);
    status_body(body,request,20,hp::READY|hp::PERSISTED,hp::PAUSED_STATE,hp::PAUSED,nullptr);
    body[1]=2; report(g_control,body,3,10); assert(g_control.result==hp::REJECTED);
    body[29]=hp::ERROR_STATE; body[32]=4; hp::put32(body+33,5); hp::put32(body+37,534);
    report(g_control,body,4,15); status_text(16,text,sizeof(text));
    assert(strstr(text,"Host operation failed") && strstr(text,"domain 4, code 5, reason 534"));
    assert(strstr(text,"Disconnect to pause") && !strstr(text,"Request rejected"));
    status_body(body,99,21,hp::READY|hp::PERSISTED,hp::PAUSED_STATE,hp::PAUSED,nullptr);
    hp::put32(body+3,88); body[32]=1; hp::put32(body+33,6);
    report(g_control,body,5,20); status_text(21,text,sizeof(text));
    assert(strstr(text,"Last operation ended") && !strstr(text,"failed"));
    status_body(body,100,22,hp::READY|hp::ADVERTISING,hp::ENROLLING,hp::ENROLL_MODE,nullptr);
    hp::put32(body+3,88); hp::put16(body+41,45);
    report(g_control,body,6,25); status_text(26,text,sizeof(text));
    assert(strstr(text,"Pair a new volume host") && !strstr(text,"Request rejected"));
    g_control=hp::Control(77); seed(g_control);
    assert(g_control.begin(hp::SELECT,6,frame,sizeof(frame)));
    status_body(body,ble_status::read32(frame+12),20,hp::READY|hp::PERSISTED|hp::FILTER_READY,hp::WAITING,hp::AUTO,A);
    report(g_control,body,3,10); assert(g_control.choose(1,11));
    status_text(11,text,sizeof(text)); assert(strstr(text,"Waiting for host-8"));
    for (unsigned connected=0;connected!=2;++connected) {
        g_control=hp::Control(77); seed(g_control); assert(g_control.choose(1,6));
        assert(g_control.begin(hp::SELECT,6,frame,sizeof(frame)));
        status_body(body,0,10,connected?CONNECT_FLAGS:hp::READY|hp::PERSISTED|hp::FILTER_READY,
                    connected?hp::CONNECTED:hp::WAITING,hp::AUTO,A);
        report(g_control,body,3,15007); assert(g_control.result==hp::TIMED_OUT);
        status_text(15008,text,sizeof(text));
        assert(strstr(text,connected?"connected to host-8":"Waiting for host-8") && !strstr(text,"host-1"));
    } // Unacknowledged SELECT cannot relabel the actual current native target.
}
''')
    binary = tmp_path / ("status.exe" if os.name == "nt" else "status")
    build = subprocess.run([compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                            "-I" + str(ROOT / "firmware/crowpanel-remote/include"), str(source), "-o", str(binary)],
                           text=True, capture_output=True)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr
