(function () {
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (err) {
        reject(err);
      } finally {
        document.body.removeChild(area);
      }
    });
  }

  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var line = btn.closest(".code-line");
      if (!line) {
        return;
      }
      var code = line.querySelector(".code-line-text");
      if (!code) {
        return;
      }
      copyText(code.textContent.trim()).then(function () {
        btn.classList.add("copied");
        btn.setAttribute("aria-label", "Copied");
        window.setTimeout(function () {
          btn.classList.remove("copied");
          btn.setAttribute("aria-label", "Copy");
        }, 2000);
      });
    });
  });
})();
