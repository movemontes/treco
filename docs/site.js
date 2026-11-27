/* Site do Treco: lê as versões publicadas no GitHub e mostra a parte do idioma da página. */
(function () {
  var REPO = "movemontes/treco";
  var lang = document.documentElement.lang.indexOf("pt") === 0 ? "pt" : "en";
  var T = {
    pt: { loading: "Carregando novidades…", fail: "Não deu para carregar as novidades agora.", latest: "NOVA", download: "Baixar", older: "Versões anteriores", copied: "Copiado!", locale: "pt-BR" },
    en: { loading: "Loading what's new…", fail: "Couldn't load what's new right now.", latest: "NEW", download: "Download", older: "Earlier versions", copied: "Copied!", locale: "en-US" }
  }[lang];

  // Lembra o idioma escolhido no seletor e, na primeira visita, leva quem não fala português para a página em inglês.
  function remember(value) { try { localStorage.setItem("treco-lang", value); } catch (e) {} }
  function remembered() { try { return localStorage.getItem("treco-lang"); } catch (e) { return null; } }
  document.querySelectorAll("[data-lang]").forEach(function (link) {
    link.addEventListener("click", function () { remember(link.getAttribute("data-lang")); });
  });
  if (lang === "pt" && !remembered() && location.search.indexOf("pt") < 0) {
    var prefs = navigator.languages || [navigator.language || "pt"];
    if (prefs.length && String(prefs[0]).toLowerCase().indexOf("pt") !== 0) {
      location.replace("en/");
      return;
    }
  }

  // Copiar a chave Pix.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy");
      var label = button.textContent;
      var done = function () { button.textContent = T.copied; setTimeout(function () { button.textContent = label; }, 1800); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
      else done();
    });
  });

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Pega só o trecho do idioma da página (entre <!-- pt --> e <!-- /pt -->). Sem marcas, usa tudo.
  function part(body) {
    body = body || "";
    var match = body.match(new RegExp("<!--\\s*" + lang + "\\s*-->([\\s\\S]*?)<!--\\s*/" + lang + "\\s*-->"));
    if (match) return match[1].trim();
    return body.replace(/<!--[\s\S]*?-->/g, "").trim();
  }

  // Markdown simples: títulos, listas, negrito, itálico, código e links.
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  }
  function markdown(text) {
    var out = [], list = false;
    text.split(/\r?\n/).forEach(function (line) {
      var item = line.match(/^\s*[-*]\s+(.*)/);
      if (item) {
        if (!list) { out.push("<ul>"); list = true; }
        out.push("<li>" + inline(item[1]) + "</li>");
        return;
      }
      if (list) { out.push("</ul>"); list = false; }
      var head = line.match(/^(#{1,4})\s+(.*)/);
      if (head) out.push("<h4>" + inline(head[2]) + "</h4>");
      else if (line.trim()) out.push("<p>" + inline(line) + "</p>");
    });
    if (list) out.push("</ul>");
    return out.join("");
  }

  function date(iso) {
    try { return new Date(iso).toLocaleDateString(T.locale, { day: "numeric", month: "long", year: "numeric" }); }
    catch (e) { return iso.slice(0, 10); }
  }
  function dmg(release) {
    var assets = release.assets || [];
    for (var i = 0; i < assets.length; i++) if (/-mac\.dmg$/i.test(assets[i].name)) return assets[i];
    return null;
  }
  function exe(release) {
    var assets = release.assets || [];
    for (var i = 0; i < assets.length; i++) if (/\.exe$/i.test(assets[i].name)) return assets[i];
    return null;
  }
  function size(bytes) { return Math.round(bytes / 1048576) + " MB"; }
  function version(release) { return (release.name && release.name.trim()) || release.tag_name; }

  var box = document.getElementById("releases");
  var meta = document.getElementById("dl-meta");
  if (!box) return;
  box.innerHTML = '<div class="loading">' + T.loading + "</div>";

  fetch("https://api.github.com/repos/" + REPO + "/releases?per_page=10", { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (list) {
      list = list.filter(function (r) { return !r.draft && !r.prerelease; });
      if (!list.length) throw new Error("empty");
      var latest = list[0], file = dmg(latest);
      var win = exe(latest);
      if (meta) meta.innerHTML = "<b>" + esc(version(latest)) + "</b> · " + meta.getAttribute("data-req");
      var html = '<article class="release"><header>' +
        '<span class="ver">' + esc(version(latest)) + "</span>" +
        '<span class="new">' + T.latest + "</span>" +
        '<span class="date">' + date(latest.published_at) + "</span>" +
        '<span class="dl">' +
        (file ? '<a class="btn small" href="' + esc(file.browser_download_url) + '">⬇ Mac · ' + size(file.size) + "</a>" : "") +
        (win ? '<a class="btn small alt" href="' + esc(win.browser_download_url) + '">⬇ Windows · ' + size(win.size) + "</a>" : "") +
        "</span>" +
        '</header><div class="notes">' + markdown(part(latest.body)) + "</div></article>";
      if (list.length > 1) {
        html += '<details class="older"><summary>' + T.older + " (" + (list.length - 1) + ")</summary>";
        list.slice(1).forEach(function (r) {
          html += '<div class="item"><header><b>' + esc(version(r)) + '</b><span class="date">' + date(r.published_at) + "</span></header>" +
            '<div class="notes">' + markdown(part(r.body)) + "</div></div>";
        });
        html += "</details>";
      }
      box.innerHTML = html;
    })
    .catch(function () {
      box.innerHTML = '<div class="release"><div class="loading">' + T.fail + "</div></div>";
    });
})();
