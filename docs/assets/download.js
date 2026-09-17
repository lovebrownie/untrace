(function () {
  var REPO = "lovebrownie/untrace";
  var API = "https://api.github.com/repos/" + REPO + "/releases/latest";

  var versionLine = document.getElementById("version-line");
  if (!versionLine) {
    return;
  }

  var assetsByPlatform = {};
  var tabWindows = document.getElementById("tab-windows");
  var tabLinux = document.getElementById("tab-linux");
  var panelWindows = document.getElementById("panel-windows");
  var panelLinux = document.getElementById("panel-linux");
  var downloadWindows = document.getElementById("download-windows");
  var downloadLinux = document.getElementById("download-linux");
  var allDownloads = document.getElementById("all-downloads");
  var allDownloadsList = document.getElementById("all-downloads-list");
  var errorEl = document.getElementById("download-error");

  function detectOsTab() {
    var ua = navigator.userAgent || "";
    var platform =
      (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    var p = platform + " " + ua;
    if (/Linux|Android|CrOS/i.test(p)) {
      return "linux";
    }
    return "windows";
  }

  function displayVersion(tag) {
    if (!tag) {
      return "Latest";
    }
    return tag.charAt(0) === "v" ? tag.slice(1) : tag;
  }

  function windowsAssetRank(name) {
    if (!/-setup\.exe$/i.test(name) || /portable/i.test(name)) {
      return -1;
    }
    if (/^untrace-v.+-\setup\.exe$/i.test(name)) {
      return 3;
    }
    if (/^untrace.+-\setup\.exe$/i.test(name)) {
      return 2;
    }
    return 1;
  }

  function resolveAssets(assets, tag) {
    var out = { windows: null, linux: null };
    (assets || []).forEach(function (asset) {
      var winRank = windowsAssetRank(asset.name);
      if (winRank >= 0) {
        var cur = out.windows;
        if (!cur || winRank > windowsAssetRank(cur.name)) {
          out.windows = {
            name: asset.name,
            url: asset.browser_download_url,
          };
        }
      }
      if (/amd64\.deb$/i.test(asset.name)) {
        out.linux = {
          name: asset.name,
          url: asset.browser_download_url,
        };
      }
    });

    if (!tag) {
      return out;
    }

    var base = "https://github.com/" + REPO + "/releases/download/" + tag + "/";
    var ver = tag.replace(/^v/i, "");

    if (!out.windows) {
      out.windows = {
        name: "Untrace-" + tag + "-Setup.exe",
        url: base + "Untrace-" + tag + "-Setup.exe",
      };
    }

    if (!out.linux) {
      out.linux = {
        name: "untrace_" + ver + "_amd64.deb",
        url: base + "untrace_" + ver + "_amd64.deb",
      };
    }

    return out;
  }

  function setTab(tab) {
    var isWin = tab === "windows";
    tabWindows.setAttribute("aria-selected", isWin ? "true" : "false");
    tabLinux.setAttribute("aria-selected", isWin ? "false" : "true");
    panelWindows.classList.toggle("active", isWin);
    panelLinux.classList.toggle("active", !isWin);
    panelWindows.hidden = !isWin;
    panelLinux.hidden = isWin;
  }

  function wireDownloadLink(el, asset, label) {
    if (!asset) {
      el.classList.add("disabled");
      el.href = "#";
      el.textContent = label + " (unavailable)";
      return;
    }
    el.classList.remove("disabled");
    el.href = asset.url;
    el.textContent = label;
  }

  function refreshButtons() {
    wireDownloadLink(downloadWindows, assetsByPlatform.windows, "Download for Windows (.exe)");
    wireDownloadLink(downloadLinux, assetsByPlatform.linux, "Download for Linux (.deb)");
  }

  function buildAllDownloadsList() {
    allDownloadsList.innerHTML = "";
    ["windows", "linux"].forEach(function (id) {
      var asset = assetsByPlatform[id];
      if (!asset) {
        return;
      }
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = asset.url;
      a.textContent = asset.name;
      li.appendChild(a);
      allDownloadsList.appendChild(li);
    });
    allDownloads.hidden = allDownloadsList.children.length === 0;
  }

  tabWindows.addEventListener("click", function () {
    setTab("windows");
  });
  tabLinux.addEventListener("click", function () {
    setTab("linux");
  });

  setTab(detectOsTab());

  fetch(API, { headers: { Accept: "application/vnd.github+json" } })
    .then(function (res) {
      if (!res.ok) {
        throw new Error("Could not load release (" + res.status + ")");
      }
      return res.json();
    })
    .then(function (release) {
      var tag = release.tag_name || "";
      versionLine.textContent = displayVersion(tag);
      versionLine.classList.remove("loading");
      assetsByPlatform = resolveAssets(release.assets, tag);
      refreshButtons();
      buildAllDownloadsList();
    })
    .catch(function (err) {
      versionLine.textContent = "Download";
      versionLine.classList.remove("loading");
      errorEl.hidden = false;
      errorEl.textContent =
        (err && err.message ? err.message : "Network error") + ". See releases on GitHub.";
      var fallback = document.createElement("a");
      fallback.href = "https://github.com/" + REPO + "/releases/latest";
      fallback.textContent = "GitHub Releases";
      fallback.style.marginLeft = "0.25rem";
      errorEl.appendChild(fallback);
    });
})();
