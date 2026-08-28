// 🎀 Modern Firefox preferences for a high-end Linux workstation.
// Policies handle telemetry and extensions; these tune profile behaviour.

// Rendering and video: retain safe fallbacks if a driver path is unavailable.
user_pref("gfx.webrender.all", true);
user_pref("media.hardware-video-decoding.enabled", true);
user_pref("media.ffmpeg.vaapi.enabled", true);
user_pref("media.av1.enabled", true);

// Make use of abundant RAM and cores while retaining Fission site isolation.
user_pref("dom.ipc.processCount", 16);
user_pref("dom.ipc.processPrelaunch.fission.number", 8);
user_pref("browser.tabs.unloadOnLowMemory", false);

// A generous disk cache is a good fit for the low-latency Optane system disk.
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.disk.smart_size.enabled", false);
user_pref("browser.cache.disk.capacity", 2097152);
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", -1);

// Privacy with low compatibility cost.
user_pref("privacy.globalprivacycontrol.enabled", true);
user_pref("privacy.query_stripping.enabled", true);
user_pref("privacy.query_stripping.enabled.pbmode", true);
user_pref("dom.private-attribution.submission.enabled", false);
user_pref("browser.contentblocking.category", "strict");

// Calm, useful browser behaviour.
user_pref("browser.tabs.warnOnClose", true);
user_pref("browser.tabs.closeWindowWithLastTab", false);
user_pref("browser.sessionstore.max_tabs_undo", 50);
user_pref("browser.ctrlTab.sortByRecentlyUsed", true);
user_pref("browser.urlbar.trimURLs", false);
user_pref("browser.urlbar.trimHttps", false);
user_pref("media.autoplay.default", 1);
user_pref("full-screen-api.warning.timeout", 0);
user_pref("ui.prefersReducedMotion", 0);
