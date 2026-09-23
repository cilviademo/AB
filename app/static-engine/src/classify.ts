/** v2 class / path classifiers and demanglers — verbatim. */

export function classifyClass(c: string): string {
  if (!c || !/^[A-Za-z_][\w:<>,]*$/.test(c) || c.replace(/::/g, '').length < 4) return 'FALSE_POSITIVE';
  if (/^(juce|Steinberg|VSTGUI|CLAP|clap)(::|$)/.test(c)) return 'FRAMEWORK';
  if (/^(soundtouch|r8b|hiir|kiss_fft|pffft|xsimd|Eigen|signalsmith|Iir|melatonin|foleys|chowdsp|rubberband|RubberBand|libsamplerate|sfizz|Gist|essentia|aubio|Elk|fftw|nlohmann|fmt|spdlog|boost|absl|google|tbb|oneapi|curl|openssl|zlib|png|jpeg|freetype|harfbuzz|hb|sqlite|SQLite|leveldb|lz4|zstd|brotli)(::|$)/.test(c)) return 'THIRD_PARTY';
  if (/^(std|stdext|Concurrency|ATL|Microsoft|__|_|type_info|DName|pDName|charNode|pcharNode|pairNode|Replicator|UnDecorator|HeapManager|basic_|allocator|exception|bad_|error_|codecvt|locale|ios_base|numpunct|ctype|money|time_|messages|collate|CLR|Cryptography)/.test(c)) return 'OS_RUNTIME';
  if (/^I(Unknown|Stream|SequentialStream|DropTarget|DropSource|DataObject|DWrite\w*|D2D1\w*|D3D\w*|DXGI\w*|RawElementProvider\w*|Accessible\w*|Dispatch|Persist\w*|ClassFactory|Malloc|Storage|PropertyStore|MMDevice\w*|Audio\w*Client|OleWindow|EnumFORMATETC|WICBitmap\w*|Shell\w*)$/.test(c)) return 'OS_RUNTIME';
  if (/^(tag|_tag|HWND__|CRITICAL_SECTION|SECURITY_ATTRIBUTES)/.test(c)) return 'OS_RUNTIME';
  return 'PLUGIN_OWNED';
}

export function classifyPath(s: string): string {
  if (/minkernel|ucrt|vctools|crt\b|\\msvc|onecore|Windows Kits|Program Files/i.test(s)) return 'CRT';
  if (/vst3sdk|pluginterfaces|public\.sdk|VST 3\.\d|AudioUnit|CoreAudio|steinberg/i.test(s)) return 'SDK';
  if (/[\\/]JUCE[\\/]modules|juce_\w+[\\/]|JuceLibraryCode|JUCE v?\d/i.test(s)) return 'FRAMEWORK';
  if (/cmake|ninja|_deps[\\/]|\.cmake$|CMakeFiles/i.test(s)) return 'BUILD_TOOL';
  if (/^[A-Za-z]:[\\/](Users|build|Jenkins|agent|actions-runner|a[\\/]1)|[\\/]ws[\\/]|[\\/]workspace[\\/]/i.test(s) && !/[\\/]Source[\\/]/i.test(s)) return 'BUILD_MACHINE';
  if (/\.(cpp|h|hpp|mm|c|jucer)$/i.test(s) && /(^|[\\/])(Source|src|DSP|UI|Plugin|include|Builds)[\\/]/i.test(s)) return 'PROJECT_SOURCE';
  if (/^[A-Za-z]:[\\/].*\.(cpp|h|hpp|mm|c|jucer)$/i.test(s)) return 'PROJECT_SOURCE';
  return 'UNKNOWN';
}

export function isUserClass(c: string): boolean { return !!c && !/^(juce|std|Steinberg|VSTGUI|__|ATL|Microsoft|stdext|Concurrency|type_info|_|CLAP|clap|foleys|chowdsp|DName|pDName|charNode|pcharNode|pairNode|Replicator|UnDecorator|HeapManager)/.test(c) && !/^(basic_|allocator|exception|bad_|error_|codecvt|locale|ios_base|numpunct|ctype|money|time_|messages|collate)/.test(c); }

export function demangleMsvcType(s: string): string {
  // .?AVName@Ns2@Ns1@@  -> Ns1::Ns2::Name ; templates (?$) kept raw-ish
  const body = s.slice(4).replace(/@@$/, '');
  const parts = body.split('@').filter(Boolean).map(p => p.replace(/^\?\$/, '')).reverse();
  return parts.join('::');
}

export function demangleItaniumType(s: string): string | null {
  let i = s.startsWith('_ZTS') ? 4 : 0, nested = false;
  if (s[i] === 'N') { nested = true; i++; }
  const parts: string[] = [];
  while (i < s.length) {
    const m = s.slice(i).match(/^(\d+)/); if (!m) break;
    const len = +m[1]; i += m[1].length; parts.push(s.substr(i, len)); i += len;
    if (!nested) break;
  }
  return parts.length ? parts.join('::') : null;
}
