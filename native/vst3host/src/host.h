#pragma once
#include <string>
#include "json.h"

namespace abhost {

/** Exit codes (EXECUTE 2.1). */
enum ExitCode { kOk = 0, kLoadFailure = 2, kPluginException = 3, kTimeout = 4, kBadRequest = 5 };

/** Run one command against one plugin. Returns the exit code; fills `response`. */
int run(const abjson::Value& request, abjson::Value& response, std::string& diagnostics);

} // namespace abhost
