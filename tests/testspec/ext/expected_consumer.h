#pragma once

#include "ext.h"

typedef struct {
	// capigen:begin appended
	int32_t (*ext_open)(const char* path, ext_db* out_db);
	void (*ext_close)(ext_db db);
	const char* (*ext_version)(void);
#if EXT_API_VERSION_AT_LEAST(1, 1, 0)
	int32_t (*ext_extra_two)(void);
#endif
#if EXT_API_ALLOW_UNSTABLE
	int32_t (*ext_flush)(ext_db db);
	EXT_KIND (*ext_get_kind)(ext_db db);
	void (*ext_extra_one)(ext_db db);
#endif
	// capigen:end appended
} ext_api;

#ifndef EXT_BUILD_STATIC
// capigen:begin appended
#define ext_open ext_api.ext_open
#define ext_close ext_api.ext_close
#define ext_version ext_api.ext_version
#if EXT_API_VERSION_AT_LEAST(1, 1, 0)
#define ext_extra_two ext_api.ext_extra_two
#endif
#if EXT_API_ALLOW_UNSTABLE
#define ext_flush ext_api.ext_flush
#endif
#if EXT_API_ALLOW_UNSTABLE
#define ext_get_kind ext_api.ext_get_kind
#endif
#if EXT_API_ALLOW_UNSTABLE
#define ext_extra_one ext_api.ext_extra_one
#endif
// capigen:end appended
#endif // EXT_BUILD_STATIC
