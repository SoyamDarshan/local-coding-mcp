(function () {
  var root = document.documentElement;
  root.classList.remove("no-js");

  var btn = document.querySelector(".theme");
  function current() {
    return root.getAttribute("data-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function label() {
    if (!btn) return;
    var dark = current() === "dark";
    btn.textContent = dark ? "Light theme" : "Dark theme";
    btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  if (btn) {
    label();
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("localexec-theme", next); } catch (e) { /* storage unavailable */ }
      label();
    });
  }

  document.querySelectorAll("pre").forEach(function (pre) {
    if (pre.closest(".ticket")) return;
    var b = document.createElement("button");
    b.type = "button";
    pre.classList.add("has-copy");
    b.className = "copy";
    b.textContent = "Copy";
    b.addEventListener("click", function () {
      var text = pre.querySelector("code").innerText;
      var done = function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1600); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { b.textContent = "Press Ctrl+C"; });
      } else {
        var range = document.createRange();
        range.selectNodeContents(pre.querySelector("code"));
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
        b.textContent = "Selected";
      }
    });
    pre.appendChild(b);
  });
})();
