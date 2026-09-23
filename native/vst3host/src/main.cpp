// vst3host entry: one JSON request on stdin (or --request-file), one JSON response on
// stdout, diagnostics on stderr. Exit codes: 0 ok · 2 load failure · 3 plugin
// exception/crash · 4 timeout (watchdog) · 5 bad request. The watchdog thread ends the
// process outright: a wedged plugin must never hang the engine (SPEC §4, §15).
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>

#include "host.h"
#include "json.h"

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

void hardExit(int code) {
    std::fflush(stdout); std::fflush(stderr);
#ifdef _WIN32
    TerminateProcess(GetCurrentProcess(), (UINT) code);
#else
    std::_Exit(code);
#endif
}

void onFatalSignal(int) {
    std::fputs("{\"ok\":false,\"error\":\"PLUGIN_CRASH\",\"detail\":\"fatal signal while the plugin was loaded\"}\n", stdout);
    hardExit(abhost::kPluginException);
}

#ifdef _WIN32
LONG WINAPI onSeh(EXCEPTION_POINTERS* ep) {
    std::fprintf(stdout, "{\"ok\":false,\"error\":\"PLUGIN_CRASH\",\"detail\":\"structured exception 0x%08lx\"}\n", (unsigned long) ep->ExceptionRecord->ExceptionCode);
    hardExit(abhost::kPluginException);
    return EXCEPTION_EXECUTE_HANDLER;
}
#endif

} // namespace

int main(int argc, char** argv) {
    std::string requestText;
    double timeoutSec = 60.0;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--version") { std::printf("vst3host %s\n", VST3HOST_VERSION); return 0; }
        if (a == "--request-file" && i + 1 < argc) { std::ifstream f(argv[++i], std::ios::binary); std::stringstream ss; ss << f.rdbuf(); requestText = ss.str(); }
        else if (a == "--request" && i + 1 < argc) requestText = argv[++i];
        else if (a == "--timeout" && i + 1 < argc) timeoutSec = std::atof(argv[++i]);
        else if (a == "--help" || a == "-h") { std::printf("usage: vst3host [--request '<json>' | --request-file f | <json on stdin>] [--timeout s]\n"); return 0; }
    }
    if (requestText.empty()) { std::stringstream ss; ss << std::cin.rdbuf(); requestText = ss.str(); }

    abjson::Value req; std::string err;
    if (!abjson::parse(requestText, req, err) || req.type != abjson::Value::Obj) {
        std::printf("{\"ok\":false,\"error\":\"BAD_REQUEST\",\"detail\":\"%s\"}\n", err.empty() ? "request must be a JSON object" : err.c_str());
        return abhost::kBadRequest;
    }
    if (req.has("timeout_s")) timeoutSec = req.num("timeout_s", timeoutSec);

    // Watchdog: hard exit 4 after the deadline, whatever the plugin is doing.
    std::thread([timeoutSec] {
        std::this_thread::sleep_for(std::chrono::milliseconds((long long) (timeoutSec * 1000.0)));
        std::fputs("{\"ok\":false,\"error\":\"HOST_TIMEOUT\",\"detail\":\"watchdog fired\"}\n", stdout);
        hardExit(abhost::kTimeout);
    }).detach();

    std::signal(SIGSEGV, onFatalSignal); std::signal(SIGILL, onFatalSignal); std::signal(SIGFPE, onFatalSignal); std::signal(SIGABRT, onFatalSignal);
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    SetUnhandledExceptionFilter(onSeh);
#endif

    abjson::Value resp = abjson::Value::object();
    std::string diag;
    int rc;
    try { rc = abhost::run(req, resp, diag); }
    catch (const std::exception& e) { diag = std::string("exception: ") + e.what(); rc = abhost::kPluginException; }
    catch (...) { diag = "unknown exception"; rc = abhost::kPluginException; }

    resp["ok"] = rc == 0;
    if (rc != 0) { resp["error"] = rc == abhost::kLoadFailure ? "LOAD_FAILURE" : rc == abhost::kBadRequest ? "BAD_REQUEST" : rc == abhost::kTimeout ? "HOST_TIMEOUT" : "PLUGIN_CRASH"; resp["detail"] = diag; }
    if (!diag.empty()) std::fprintf(stderr, "%s\n", diag.c_str());
    std::string text = abjson::dump(resp);
    std::fwrite(text.data(), 1, text.size(), stdout); std::fputc('\n', stdout);
    hardExit(rc); // never return through the plugin's static destructors
}
