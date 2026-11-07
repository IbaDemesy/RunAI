(function (root, factory) {
  const partners = factory();
  if (typeof module === "object" && module.exports) module.exports = partners;
  else root.RunAIPartners = partners;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function partnerFor(x = {}) {
    const candidate = x.candidate || x;
    const turn = x.framing?.turns?.slice().reverse().find(turn => turn.role === "assistant");
    const provider = x.event?.provider || x.step?.provider || candidate.provider || turn?.provider;
    let id = String(provider || "").toLowerCase().replace(/^h\//, "");
    if (["h company", "web-surfer-pro"].includes(id)) id = "h";
    if (["holo4", "holo"].includes(id)) id = "holo";
    if (id === "solaria-1") id = "gladia";
    // Fallbacks: agent traces use H, search candidates use Linkup, assistant turns use Holo, voice uses Gladia.
    if (!provider) {
      const source = x.event?.source || x.step?.source || x.source;
      if (source === "h" || source?.startsWith("agent:")) id = "h";
      else if (candidate.sources || x.framing?.candidates?.length) id = "linkup";
      else if (x.role === "assistant" || turn) id = "holo";
      else if (x.voice || x.voiceState || x.type === "voice" || x.channel === "voice") id = "gladia";
    }
    const n = candidate.sources?.length || 0;
    const latency = candidate.latency_ms == null ? "" : " · " + (candidate.latency_ms / 1000).toFixed(1) + " s";
    const labels = { h: "H web-surfer-pro", linkup: "Found by Linkup · " + n + (n === 1 ? " source" : " sources") + latency,
      holo: "Framed by Holo4 (H Company)", gladia: "Voice by Gladia solaria-1 · live", devin: "Built with Devin" };
    return labels[id] ? { id, label: labels[id], detail: labels[id] } : null;
  }
  function decorate(screen, ctx = {}) {
    const doc = screen?.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!screen?.querySelectorAll || !doc?.createElement) return;
    const make = (tag, text, className) => {
      const node = doc.createElement(tag);
      if (text != null) node.textContent = text;
      if (className) node.className = className;
      return node;
    };
    const marked = node => node.dataset?.partner || node.getAttribute?.("data-partner") || Array.from(node.children || []).some(marked);
    const badge = (node, partner) => {
      if (!partner || marked(node)) return false;
      const p = make("p", partner.label, "partner-badge");
      p.setAttribute("data-partner", partner.id); node.append(p); return true;
    };
    for (const card of screen.querySelectorAll(".candidate")) {
      const heading = Array.from(card.children || []).find(node => /^H[1-6]$/i.test(node.tagName));
      const candidate = ctx.framing?.candidates?.find(candidate => candidate.name === heading?.textContent);
      if (!candidate || !badge(card, partnerFor({ candidate }))) continue;
      const sources = candidate.sources || [];
      const details = make("details", null, "sources");
      details.append(make("summary", "Sources (" + sources.length + ")"));
      const list = make("ul");
      for (const source of sources) {
        try {
          const url = new URL(source.url);
          if (!["http:", "https:"].includes(url.protocol)) continue;
          const a = make("a", source.title || url.hostname);
          a.href = url.href; a.target = "_blank"; a.rel = "noopener noreferrer";
          const li = make("li"); li.append(a); list.append(li);
        } catch (_) { /* Invalid URLs are not links. */ }
      }
      details.append(list); card.append(details);
    }
    for (const node of screen.querySelectorAll(".say")) {
      if (marked(node)) continue;
      const partner = partnerFor({ framing: { turns: ctx.framing?.turns || [] }, role: "assistant" });
      if (!partner || !node.parentNode) continue;
      const caption = make("p", partner.label, "partner-badge");
      caption.setAttribute("data-partner", partner.id); node.setAttribute("data-partner", partner.id);
      if (node.parentNode.insertBefore) node.parentNode.insertBefore(caption, node.nextSibling || null);
      else node.parentNode.append(caption);
    }
    for (const node of screen.querySelectorAll(".voice-controls")) badge(node, partnerFor({ voice: true }));
    for (const [index, node] of Array.from(screen.querySelectorAll(".lane")).entries()) badge(node, partnerFor({ step: ctx.mission?.steps?.[index], source: "h" }));
    const mode = doc.getElementById?.("mode");
    const parent = mode?.parentNode;
    if (parent?.insertBefore && !Array.from(parent.children || []).some(node => String(node.className).split(/\s+/).includes("powered-by"))) {
      parent.insertBefore(make("span", "Powered by H Company · Linkup · Gladia · built with Devin", "powered-by"), mode);
    }
  }
  return { partnerFor, decorate };
});
