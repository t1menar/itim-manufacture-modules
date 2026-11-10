(function () {
  try {
    var key = "mf-color-scheme";
    var t = localStorage.getItem(key);
    if (t !== "light" && t !== "dark") {
      t = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    document.documentElement.setAttribute("data-mantine-color-scheme", t);
  } catch (e) {
    /* ignore */
  }
})();
