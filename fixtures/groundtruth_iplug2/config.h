// iPlug2 configuration for ground-truth fixture #2 (ADDENDUM A5). Values mirror ../groundtruth/spec.json.
#define PLUG_NAME "ABGroundTruthIP"
#define PLUG_MFR "Multibanded"
#define PLUG_VERSION_HEX 0x00010000
#define PLUG_VERSION_STR "1.0.0"
#define PLUG_UNIQUE_ID 'Abgi'
#define PLUG_MFR_ID 'Mbnd'
#define PLUG_URL_STR ""
#define PLUG_EMAIL_STR ""
#define PLUG_COPYRIGHT_STR "Copyright Multibanded — ground-truth fixture, no rights implied"
#define PLUG_CLASS_NAME ABGroundTruthIP

#define BUNDLE_NAME "ABGroundTruthIP"
#define BUNDLE_MFR "Multibanded"
#define BUNDLE_DOMAIN "com"

#define SHARED_RESOURCES_SUBPATH "ABGroundTruthIP"

#define PLUG_CHANNEL_IO "2-2"

#define PLUG_LATENCY 0
#define PLUG_TYPE 0
#define PLUG_DOES_MIDI_IN 0
#define PLUG_DOES_MIDI_OUT 0
#define PLUG_DOES_MPE 0
#define PLUG_DOES_STATE_CHUNKS 1
#define PLUG_HAS_UI 1
#define PLUG_WIDTH 520
#define PLUG_HEIGHT 260
#define PLUG_FPS 60
#define PLUG_SHARED_RESOURCES 0
#define PLUG_HOST_RESIZE 0

#define AUV2_ENTRY ABGroundTruthIP_Entry
#define AUV2_ENTRY_STR "ABGroundTruthIP_Entry"
#define AUV2_FACTORY ABGroundTruthIP_Factory
#define AUV2_VIEW_CLASS ABGroundTruthIP_View
#define AUV2_VIEW_CLASS_STR "ABGroundTruthIP_View"

#define AAX_TYPE_IDS 'ABG1'
#define AAX_TYPE_IDS_AUDIOSUITE 'ABG2'
#define AAX_PLUG_MFR_STR "Multibanded"
#define AAX_PLUG_NAME_STR "ABGroundTruthIP\nABGT"
#define AAX_PLUG_CATEGORY_STR "Effect"
#define AAX_DOES_AUDIOSUITE 0

#define VST3_SUBCATEGORY "Fx|Distortion"

#define APP_NUM_CHANNELS 2
#define APP_N_VECTOR_WAIT 0
#define APP_MULT 1
#define APP_COPY_AUV3 0
#define APP_SIGNAL_VECTOR_SIZE 64

// resources (Windows .rc / macOS bundle) — same bytes as ../groundtruth/Resources and Presets
#define KNOB_FN "knob.png"
#define ABMONO_FN "ABMono.ttf"
#define INIT_FN "Init.xml"
