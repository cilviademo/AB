// vst3host — the only AB process that loads a plugin (SPEC §7, §15).
//
// Commands (request.command): factory · parameters · units · buses · info · state ·
// setparam · render. Every command loads the module fresh, instantiates component +
// controller through the SDK's PlugProvider, runs, and tears down; nothing is shared
// with the caller and nothing stays loaded between commands.
#include "host.h"
#include "probes.h"
#include "wav.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <memory>
#include <numeric>
#include <sstream>
#include <vector>

#include "base/source/fobject.h"
#include "pluginterfaces/base/funknown.h"
#include "pluginterfaces/base/ustring.h"
#include "pluginterfaces/gui/iplugview.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivstcomponent.h"
#include "pluginterfaces/vst/ivsteditcontroller.h"
#include "pluginterfaces/vst/ivstparameterchanges.h"
#include "pluginterfaces/vst/ivstprocesscontext.h"
#include "pluginterfaces/vst/ivstunits.h"
#include "pluginterfaces/vst/vsttypes.h"
#include "public.sdk/source/common/memorystream.h"
#include "public.sdk/source/vst/hosting/eventlist.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/parameterchanges.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/processdata.h"
#include "public.sdk/source/vst/utility/stringconvert.h"

using namespace Steinberg;
using namespace Steinberg::Vst;
using abjson::Value;

namespace abhost {

namespace {

std::string toUtf8(const TChar* s) { return VST3::StringConvert::convert(s); }

std::string uidString(const VST3::UID& uid) { return uid.toString(); }
std::string fuidString(const FUID& f) { char buf[64]; f.toString(buf); return buf; }

struct Loaded {
    VST3::Hosting::Module::Ptr module;
    std::unique_ptr<VST3::Hosting::ClassInfo> classInfo;
    IPtr<PlugProvider> provider;
    IComponent* component = nullptr;
    IEditController* controller = nullptr;
    IPtr<IAudioProcessor> processor;
    ~Loaded() {
        if (provider && (component || controller)) provider->releasePlugIn(component, controller);
        component = nullptr; controller = nullptr;
        provider = nullptr; module = nullptr;
    }
};

HostApplication& hostApp() { static HostApplication app; return app; }

int loadModule(const std::string& path, Loaded& L, std::string& diag) {
    std::string err;
    L.module = VST3::Hosting::Module::create(path, err);
    if (!L.module) { diag = "module load failed: " + err; return kLoadFailure; }
    return kOk;
}

int selectClass(const Value& req, Loaded& L, std::string& diag) {
    auto infos = L.module->getFactory().classInfos();
    int index = (int) req.num("class_index", -1);
    int seen = 0;
    for (auto& ci : infos) {
        if (ci.category() != kVstAudioEffectClass) continue;
        if (index < 0 || seen == index) { L.classInfo = std::make_unique<VST3::Hosting::ClassInfo>(ci); return kOk; }
        seen++;
    }
    diag = "no Audio Module Class at class_index " + std::to_string(index);
    return kLoadFailure;
}

int instantiate(const Value& req, Loaded& L, std::string& diag) {
    int rc = selectClass(req, L, diag);
    if (rc) return rc;
    PluginContextFactory::instance().setPluginContext(&hostApp());
    L.provider = owned(NEW PlugProvider(L.module->getFactory(), *L.classInfo, true));
    if (!L.provider->initialize()) { diag = "PlugProvider::initialize failed (component/controller could not be created)"; return kLoadFailure; }
    L.component = L.provider->getComponent();
    L.controller = L.provider->getController();
    if (!L.component) { diag = "no IComponent"; return kLoadFailure; }
    L.processor = FUnknownPtr<IAudioProcessor>(L.component);
    return kOk;
}

Value factoryJson(Loaded& L) {
    auto& f = L.module->getFactory();
    auto info = f.info();
    Value out = Value::object();
    out["vendor"] = info.vendor(); out["url"] = info.url(); out["email"] = info.email(); out["flags"] = (int) info.flags();
    out["class_count"] = (int) f.classCount();
    Value classes = Value::array();
    for (auto& ci : f.classInfos()) {
        Value c = Value::object();
        c["name"] = ci.name(); c["cid"] = uidString(ci.ID()); c["category"] = ci.category(); c["subcategories"] = ci.subCategoriesString();
        c["vendor"] = ci.vendor(); c["version"] = ci.version(); c["sdk"] = ci.sdkVersion(); c["cardinality"] = ci.cardinality(); c["class_flags"] = (int) ci.classFlags();
        classes.push(c);
    }
    out["classes"] = classes;
    out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

Value parametersJson(Loaded& L) {
    Value out = Value::array();
    if (!L.controller) return out;
    int32 n = L.controller->getParameterCount();
    for (int32 i = 0; i < n; ++i) {
        ParameterInfo pi{};
        if (L.controller->getParameterInfo(i, pi) != kResultOk) continue;
        Value p = Value::object();
        p["index"] = i; p["param_id"] = (uint32_t) pi.id; p["title"] = toUtf8(pi.title); p["short_title"] = toUtf8(pi.shortTitle); p["units"] = toUtf8(pi.units);
        p["step_count"] = pi.stepCount; p["default_normalized"] = pi.defaultNormalizedValue; p["flags"] = pi.flags; p["unit_id"] = pi.unitId;
        p["can_automate"] = (pi.flags & ParameterInfo::kCanAutomate) != 0; p["is_readonly"] = (pi.flags & ParameterInfo::kIsReadOnly) != 0;
        p["is_bypass"] = (pi.flags & ParameterInfo::kIsBypass) != 0; p["is_list"] = (pi.flags & ParameterInfo::kIsList) != 0; p["is_hidden"] = (pi.flags & ParameterInfo::kIsHidden) != 0;
        p["current_normalized"] = L.controller->getParamNormalized(pi.id);
        Value samples = Value::array();
        for (double v : {0.0, 0.25, 0.5, 0.75, 1.0}) {
            String128 s{}; Value row = Value::object(); row["normalized"] = v;
            if (L.controller->getParamStringByValue(pi.id, v, s) == kResultOk) {
                row["string"] = toUtf8(s);
                ParamValue back = -1;
                if (L.controller->getParamValueByString(pi.id, s, back) == kResultOk) row["round_trip_normalized"] = back;
                else row["round_trip_normalized"] = nullptr;
            } else row["string"] = nullptr;
            row["plain"] = L.controller->normalizedParamToPlain(pi.id, v);
            samples.push(row);
        }
        p["samples"] = samples;
        p["evidence"] = "VERIFIED_RUNTIME";
        out.push(p);
    }
    return out;
}

Value unitsJson(Loaded& L) {
    Value out = Value::object();
    Value units = Value::array(), lists = Value::array();
    FUnknownPtr<IUnitInfo> ui(L.controller);
    if (ui) {
        for (int32 i = 0; i < ui->getUnitCount(); ++i) { UnitInfo u{}; if (ui->getUnitInfo(i, u) != kResultOk) continue; Value v = Value::object(); v["id"] = u.id; v["parent_id"] = u.parentUnitId; v["name"] = toUtf8(u.name); v["program_list_id"] = u.programListId; units.push(v); }
        for (int32 i = 0; i < ui->getProgramListCount(); ++i) { ProgramListInfo pl{}; if (ui->getProgramListInfo(i, pl) != kResultOk) continue; Value v = Value::object(); v["id"] = pl.id; v["name"] = toUtf8(pl.name); v["program_count"] = pl.programCount;
            Value names = Value::array(); for (int32 k = 0; k < std::min<int32>(pl.programCount, 512); ++k) { String128 s{}; if (ui->getProgramName(pl.id, k, s) == kResultOk) names.push(toUtf8(s)); } v["programs"] = names; lists.push(v); }
        out["selected_unit"] = ui->getSelectedUnit();
    }
    out["units"] = units; out["program_lists"] = lists; out["supported"] = (bool) ui; out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

Value busesJson(Loaded& L) {
    Value out = Value::object();
    for (auto dir : {kInput, kOutput}) {
        for (auto type : {kAudio, kEvent}) {
            Value arr = Value::array();
            int32 n = L.component->getBusCount(type, dir);
            for (int32 i = 0; i < n; ++i) {
                BusInfo bi{}; if (L.component->getBusInfo(type, dir, i, bi) != kResultOk) continue;
                Value b = Value::object(); b["index"] = i; b["name"] = toUtf8(bi.name); b["channel_count"] = bi.channelCount; b["bus_type"] = bi.busType == kMain ? "main" : "aux"; b["default_active"] = (bi.flags & BusInfo::kDefaultActive) != 0; b["flags"] = (int) bi.flags;
                if (type == kAudio && L.processor) { SpeakerArrangement sa = 0; if (L.processor->getBusArrangement(dir, i, sa) == kResultOk) { std::ostringstream h; h << "0x" << std::hex << (unsigned long long) sa; b["arrangement"] = h.str(); b["arrangement_channels"] = SpeakerArr::getChannelCount(sa); } }
                arr.push(b);
            }
            out[std::string(dir == kInput ? "input" : "output") + "_" + (type == kAudio ? "audio" : "event")] = arr;
        }
    }
    out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

Value infoJson(Loaded& L, double sr, int32 block) {
    Value out = Value::object();
    if (L.processor) {
        ProcessSetup setup{ kRealtime, kSample32, block, sr };
        out["can_process_32"] = L.processor->canProcessSampleSize(kSample32) == kResultTrue;
        out["can_process_64"] = L.processor->canProcessSampleSize(kSample64) == kResultTrue;
        L.component->setActive(false);
        out["setup_processing"] = L.processor->setupProcessing(setup) == kResultOk;
        L.component->setActive(true);
        out["latency_samples"] = (int) L.processor->getLatencySamples();
        uint32 tail = L.processor->getTailSamples();
        out["tail_samples"] = tail == kInfiniteTail ? Value("infinite") : tail == kNoTail ? Value(0) : Value((int) tail);
        FUnknownPtr<IProcessContextRequirements> pcr(L.processor);
        out["process_context_requirements"] = pcr ? (int) pcr->getProcessContextRequirements() : -1;
        L.component->setActive(false);
    }
    Value editor = Value::object();
    editor["available"] = false;
    if (L.controller) {
        IPlugView* view = L.controller->createView(ViewType::kEditor);
        if (view) {
            editor["available"] = true;
            ViewRect r{}; if (view->getSize(&r) == kResultOk) { editor["width"] = r.getWidth(); editor["height"] = r.getHeight(); }
            editor["resizable"] = view->canResize() == kResultTrue;
            editor["platform_hwnd"] = view->isPlatformTypeSupported(kPlatformTypeHWND) == kResultTrue;
            editor["platform_x11"] = view->isPlatformTypeSupported(kPlatformTypeX11EmbedWindowID) == kResultTrue;
            view->release();
        }
    }
    out["editor"] = editor;
    out["sample_rate"] = sr; out["block_size"] = block; out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

std::string streamB64(MemoryStream& ms) { return abjson::base64((const unsigned char*) ms.getData(), (size_t) ms.getSize()); }

/** Run one silent process block carrying parameter changes, so a JUCE-style component's
    internal state reflects them before getState (state-differential harness, SPEC §7). */
bool applyParams(Loaded& L, const Value* params, double sr, int32 block, std::string& diag) {
    if (!L.processor) { diag = "no IAudioProcessor"; return false; }
    ProcessSetup setup{ kRealtime, kSample32, block, sr };
    L.component->setActive(false);
    if (L.processor->setupProcessing(setup) != kResultOk) { diag = "setupProcessing failed"; return false; }
    for (auto dir : {kInput, kOutput}) for (int32 i = 0; i < L.component->getBusCount(kAudio, dir); ++i) L.component->activateBus(kAudio, dir, i, true);
    L.component->setActive(true);
    L.processor->setProcessing(true);
    HostProcessData data;
    data.prepare(*L.component, block, kSample32);
    data.numSamples = block; data.processMode = kRealtime; data.symbolicSampleSize = kSample32;
    ParameterChanges changes; EventList events;
    if (params && params->type == Value::Obj) {
        for (auto& kv : *params->o) {
            ParamID id = (ParamID) std::stoul(kv.first);
            if (L.controller) L.controller->setParamNormalized(id, kv.second.n);
            int32 idx = 0; if (auto* q = changes.addParameterData(id, idx)) { int32 pidx = 0; q->addPoint(0, kv.second.n, pidx); }
        }
    }
    data.inputParameterChanges = &changes; data.inputEvents = &events;
    for (int32 i = 0; i < data.numInputs; ++i) for (int32 c = 0; c < data.inputs[i].numChannels; ++c) std::memset(data.inputs[i].channelBuffers32[c], 0, sizeof(float) * block);
    L.processor->process(data);
    L.processor->setProcessing(false);
    L.component->setActive(false);
    data.unprepare();
    return true;
}

Value stateJson(Loaded& L, std::string& diag) {
    Value out = Value::object();
    MemoryStream cs, ks;
    if (L.component->getState(&cs) == kResultOk) { out["component_state_b64"] = streamB64(cs); out["component_state_size"] = (int) cs.getSize(); }
    else out["component_state_b64"] = nullptr;
    if (L.controller && L.controller->getState(&ks) == kResultOk) { out["controller_state_b64"] = streamB64(ks); out["controller_state_size"] = (int) ks.getSize(); }
    else out["controller_state_b64"] = nullptr;
    // A decoded UTF-8/XML view helps the correlation stage when the state is text (JUCE wraps XML in a small binary header).
    std::string text((const char*) cs.getData(), (size_t) cs.getSize());
    size_t lt = text.find('<');
    if (lt != std::string::npos) { size_t end = text.find_last_of('>'); if (end != std::string::npos && end > lt) out["component_state_text"] = text.substr(lt, end - lt + 1); }
    out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

bool restoreState(Loaded& L, const Value& req) {
    std::string b64 = req.str("component_state_b64");
    if (b64.empty()) return true;
    auto bytes = abjson::unbase64(b64);
    MemoryStream ms((void*) bytes.data(), (TSize) bytes.size());
    if (L.component->setState(&ms) != kResultOk) return false;
    if (L.controller) { MemoryStream ms2((void*) bytes.data(), (TSize) bytes.size()); L.controller->setComponentState(&ms2); }
    return true;
}

Value renderJson(Loaded& L, const Value& req, std::string& diag, int& rc) {
    Value out = Value::object();
    double sr = req.num("sample_rate", 48000.0);
    int32 block = (int32) req.num("block_size", 256);
    std::string probe = req.str("probe", "impulse");
    size_t frames = (size_t) req.num("frames", (double) (size_t) (sr * 2.0));
    std::string outPath = req.str("out");
    auto x = abprobe::make(probe, frames, sr);
    if (x.empty()) { diag = "unknown probe " + probe; rc = kBadRequest; return out; }

    ProcessSetup setup{ kRealtime, kSample32, block, sr };
    L.component->setActive(false);
    if (!L.processor || L.processor->setupProcessing(setup) != kResultOk) { diag = "setupProcessing failed"; rc = kPluginException; return out; }
    for (auto dir : {kInput, kOutput}) for (int32 i = 0; i < L.component->getBusCount(kAudio, dir); ++i) L.component->activateBus(kAudio, dir, i, true);
    L.component->setActive(true);
    L.processor->setProcessing(true);
    int32 latency = L.processor->getLatencySamples();

    HostProcessData data;
    data.prepare(*L.component, block, kSample32);
    data.processMode = kRealtime; data.symbolicSampleSize = kSample32;
    ParameterChanges changes; EventList events;
    ProcessContext ctx{}; ctx.sampleRate = sr; ctx.state = ProcessContext::kPlaying | ProcessContext::kTempoValid; ctx.tempo = 120.0;
    data.processContext = &ctx; data.inputEvents = &events; data.inputParameterChanges = &changes;
    // parameter snapshot in the first block
    if (auto* params = req.get("params"); params && params->type == Value::Obj)
        for (auto& kv : *params->o) { ParamID id = (ParamID) std::stoul(kv.first); if (L.controller) L.controller->setParamNormalized(id, kv.second.n); int32 idx = 0; if (auto* q = changes.addParameterData(id, idx)) { int32 p = 0; q->addPoint(0, kv.second.n, p); } }

    int32 nOutCh = data.numOutputs > 0 ? data.outputs[0].numChannels : 0;
    int32 nInCh = data.numInputs > 0 ? data.inputs[0].numChannels : 0;
    std::vector<std::vector<float>> rendered((size_t) std::max<int32>(nOutCh, 1), std::vector<float>(frames, 0.0f));
    double peak = 0, sumsq = 0; bool nonFinite = false;
    for (size_t pos = 0; pos < frames; pos += (size_t) block) {
        int32 n = (int32) std::min<size_t>((size_t) block, frames - pos);
        data.numSamples = n;
        for (int32 i = 0; i < data.numInputs; ++i) for (int32 c = 0; c < data.inputs[i].numChannels; ++c) { float* d = data.inputs[i].channelBuffers32[c]; for (int32 k = 0; k < n; ++k) d[k] = (i == 0) ? x[pos + (size_t) k] : 0.0f; }
        for (int32 i = 0; i < data.numOutputs; ++i) for (int32 c = 0; c < data.outputs[i].numChannels; ++c) std::memset(data.outputs[i].channelBuffers32[c], 0, sizeof(float) * (size_t) n);
        ctx.projectTimeSamples = (TSamples) pos; ctx.continousTimeSamples = (TSamples) pos;
        L.processor->process(data);
        if (pos == 0) { changes.clearQueue(); }
        for (int32 c = 0; c < nOutCh; ++c) { const float* d = data.outputs[0].channelBuffers32[c]; for (int32 k = 0; k < n; ++k) { float v = d[k]; if (!std::isfinite(v)) { nonFinite = true; v = 0.0f; } rendered[(size_t) c][pos + (size_t) k] = v; double a = std::fabs(v); if (a > peak) peak = a; sumsq += (double) v * v; } }
    }
    L.processor->setProcessing(false);
    L.component->setActive(false);
    data.unprepare();

    // measured latency: first sample of |y| above 1e-6 for the impulse probe (relative to the reported one)
    int measuredLatency = -1;
    if (probe == "impulse" && nOutCh > 0) for (size_t i = 0; i < frames; ++i) if (std::fabs(rendered[0][i]) > 1e-6f) { measuredLatency = (int) i; break; }
    // tail: last sample above -100 dBFS after the input ended (ramp/sine/impulse all end at `frames`)
    int tail = 0;
    if (nOutCh > 0) for (size_t i = frames; i-- > 0;) if (std::fabs(rendered[0][i]) > 1e-5f) { tail = (int) i; break; }
    // transfer curve for the ramp probe: (x, y) pairs decimated to 512 points, latency-compensated
    Value transfer = Value::array();
    if (probe == "ramp" && nOutCh > 0) {
        int lat = latency > 0 ? latency : std::max(0, measuredLatency);
        size_t lead = abprobe::rampLeadIn(frames);
        size_t step = std::max<size_t>(1, (frames - lead) / 512);
        for (size_t i = lead; i + (size_t) lat < frames; i += step) { Value pt = Value::array(); pt.push((double) x[i]); pt.push((double) rendered[0][i + (size_t) lat]); transfer.push(pt); }
    }
    if (!outPath.empty()) { if (!abwav::write(outPath, rendered, (int) sr)) { diag = "could not write " + outPath; rc = kBadRequest; return out; } out["wav"] = outPath; }
    out["probe"] = probe; out["sample_rate"] = sr; out["block_size"] = block; out["frames"] = (int) frames; out["channels"] = nOutCh; out["input_channels"] = nInCh;
    out["peak"] = peak; out["rms"] = std::sqrt(sumsq / std::max<size_t>(1, frames * (size_t) std::max<int32>(nOutCh, 1)));
    out["latency_reported"] = (int) latency; out["latency_measured"] = measuredLatency; out["tail_last_sample"] = tail; out["non_finite"] = nonFinite;
    out["transfer_curve"] = transfer; out["evidence"] = "VERIFIED_RUNTIME";
    return out;
}

} // namespace

int run(const Value& req, Value& resp, std::string& diag) {
    std::string cmd = req.str("command");
    std::string plugin = req.str("plugin");
    if (cmd.empty() || plugin.empty()) { diag = "request needs {command, plugin}"; return kBadRequest; }
    static const char* known[] = {"factory", "parameters", "units", "buses", "info", "state", "setparam", "render"};
    if (std::find(std::begin(known), std::end(known), cmd) == std::end(known)) { diag = "unknown command " + cmd; return kBadRequest; }
    double sr = req.num("sample_rate", 48000.0); int32 block = (int32) req.num("block_size", 256);

    Loaded L;
    int rc = loadModule(plugin, L, diag);
    if (rc) return rc;
    resp["plugin"] = plugin; resp["command"] = cmd; resp["host"] = std::string("vst3host ") + VST3HOST_VERSION; resp["sdk"] = kVstVersionString;
    if (cmd == "factory") { resp["data"] = factoryJson(L); return kOk; }
    rc = instantiate(req, L, diag);
    if (rc) return rc;
    resp["class"] = Value::object(); resp["class"]["name"] = L.classInfo->name(); resp["class"]["cid"] = uidString(L.classInfo->ID());
    if (L.controller) { TUID cid{}; if (L.component->getControllerClassId(cid) == kResultOk) resp["class"]["controller_cid"] = fuidString(FUID::fromTUID(cid)); }
    if (!restoreState(L, req)) { diag = "setState with the supplied state failed"; return kPluginException; }
    if (cmd == "parameters") resp["data"] = parametersJson(L);
    else if (cmd == "units") resp["data"] = unitsJson(L);
    else if (cmd == "buses") resp["data"] = busesJson(L);
    else if (cmd == "info") resp["data"] = infoJson(L, sr, block);
    else if (cmd == "state") { if (req.has("params") && !applyParams(L, req.get("params"), sr, block, diag)) return kPluginException; resp["data"] = stateJson(L, diag); }
    else if (cmd == "setparam") { if (!applyParams(L, req.get("params"), sr, block, diag)) return kPluginException; resp["data"] = stateJson(L, diag); if (L.controller && req.get("params")) { Value now = Value::object(); for (auto& kv : *req.get("params")->o) now[kv.first] = L.controller->getParamNormalized((ParamID) std::stoul(kv.first)); resp["data"]["controller_values"] = now; } }
    else if (cmd == "render") { int rrc = kOk; resp["data"] = renderJson(L, req, diag, rrc); if (rrc) return rrc; }
    return kOk;
}

} // namespace abhost
