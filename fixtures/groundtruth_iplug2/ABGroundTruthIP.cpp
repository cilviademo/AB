#include "ABGroundTruthIP.h"
#include "IPlug_include_in_plug_src.h"
#include "IControls.h"
#include <cmath>

ABGroundTruthIP::ABGroundTruthIP (const InstanceInfo& info)
    : Plugin (info, MakeConfig (kNumParams, 1))
{
    ABGT_INIT_PARAMS();
    (void) license.isLicensed();

#if IPLUG_EDITOR
    mMakeGraphicsFunc = [&]() { return MakeGraphics (*this, PLUG_WIDTH, PLUG_HEIGHT, PLUG_FPS, GetScaleForScreen (PLUG_WIDTH, PLUG_HEIGHT)); };
    mLayoutFunc = [&](IGraphics* pGraphics) {
        pGraphics->AttachPanelBackground (COLOR_GRAY);
        pGraphics->LoadFont ("ABMono", ABMONO_FN);
        const IBitmap knob = pGraphics->LoadBitmap (KNOB_FN, 1);
        const IRECT b = pGraphics->GetBounds().GetPadded (-10.f);
        for (int i = 0; i < kNumParams; ++i)
            pGraphics->AttachControl (new IBKnobControl (b.GetGridCell (i, 2, 4), knob, i));
    };
#endif
}

void ABGroundTruthIP::OnReset()
{
    const double sr = GetSampleRate();
    for (auto& f : filter) f.prepare (sr);
    for (auto& o : oversampler) o.reset();
    smoothCoef = (float) std::exp (-1.0 / (0.02 * sr));
    updateFromParameters();
    inGainZ = inGain;
    outGainZ = outGain;
    SetLatency (GetParam (kOversample)->Bool() ? oversampler[0].latency() : 0);
}

void ABGroundTruthIP::OnParamChange (int) { updateFromParameters(); }

void ABGroundTruthIP::updateFromParameters()
{
    for (auto& f : filter) f.setCutoff ((float) GetParam (kCutoff)->Value());
    const int m = GetParam (kMode)->Int();
    shaper.setDrive ((float) GetParam (kDrive)->Value() * (m == 2 ? 2.0f : 1.0f));
    inGain  = (float) std::pow (10.0, GetParam (kInputGain)->Value() / 20.0);
    outGain = (float) std::pow (10.0, GetParam (kOutputGain)->Value() / 20.0);
}

void ABGroundTruthIP::ProcessBlock (sample** inputs, sample** outputs, int nFrames)
{
    const int nCh = NOutChansConnected() < 2 ? NOutChansConnected() : 2;
    if (GetParam (kBypass)->Bool())
    {
        for (int c = 0; c < nCh; ++c)
            for (int i = 0; i < nFrames; ++i) outputs[c][i] = inputs[c][i];
        return;
    }
    const bool clean = GetParam (kMode)->Int() == 0;
    const bool os = GetParam (kOversample)->Bool();
    for (int c = 0; c < nCh; ++c)
    {
        float gi = inGainZ, go = outGainZ;
        for (int i = 0; i < nFrames; ++i)
        {
            gi = smoothCoef * gi + (1.0f - smoothCoef) * inGain;
            go = smoothCoef * go + (1.0f - smoothCoef) * outGain;
            float x = filter[c].process ((float) inputs[c][i] * gi);
            if (! clean)
                x = os ? oversampler[c].process (x, [this] (float v) { return shaper.process (v); }) : shaper.process (x);
            outputs[c][i] = x * go;
        }
        if (c == nCh - 1) { inGainZ = gi; outGainZ = go; }
    }
}

bool ABGroundTruthIP::SerializeState (IByteChunk& chunk) const
{
    bool ok = SerializeParams (chunk);
    for (const auto& f : kStateOnly)
    {
        const float v = (std::string (f.id) == "waveShapers_0_1") ? waveShapers_0_1 : uiScale;
        chunk.PutStr (f.id);
        chunk.Put (&v);
    }
    return ok;
}

int ABGroundTruthIP::UnserializeState (const IByteChunk& chunk, int startPos)
{
    int pos = UnserializeParams (chunk, startPos);
    for (size_t k = 0; k < sizeof (kStateOnly) / sizeof (kStateOnly[0]); ++k)
    {
        WDL_String id;
        float v = 0.0f;
        pos = chunk.GetStr (id, pos);
        pos = chunk.Get (&v, pos);
        if (pos < 0) break;
        if (std::string (id.Get()) == "waveShapers_0_1") waveShapers_0_1 = v; else uiScale = v;
    }
    OnReset();
    return pos;
}
