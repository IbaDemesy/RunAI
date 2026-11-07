(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RunAIVoiceInput = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const chapters = {
    home: ["maison", "domicile", "home"],
    departure_hub: ["gare", "aeroport", "departure hub", "station", "airport"],
    main_transport: ["trajet", "transport", "train", "vol", "journey", "flight"],
    arrival_hotel: ["hotel"],
    bib_pickup: ["dossard", "retrait du dossard", "bib pickup", "bib"],
    race: ["course", "race"],
    return_trip: ["retour", "return trip", "return"],
  };

  function parseJourneyCommand(transcript) {
    const text = transcript.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/’/g, "'").trim().replace(/[.!?]+$/, "").replace(/\s+/g, " ");
    const camera = "(?:la |le |the )?(?:camera|survol|flyover)";
    if (new RegExp(`^(?:pause|arrete|stop|mets en pause|pause the) ${camera}$`).test(text))
      return { target: "camera", action: "pause" };
    if (new RegExp(`^(?:reprends|continue|relance|resume|play) ${camera}$`).test(text))
      return { target: "camera", action: "play" };
    if (/^(?:(?:pause|stop|mets en pause)(?: (?:les |the )?agents)?|agents pause)$/.test(text))
      return { target: "agents", action: "pause" };
    if (/^(?:(?:reprends|continue|resume)(?: (?:les |the )?agents)?|agents resume)$/.test(text))
      return { target: "agents", action: "resume" };
    const km = text.match(/^(?:(?:va au|go to) )?(?:km|kilometre|kilometer|kilometres|kilometers) (\d+(?:[.,]\d+)?)$/);
    if (km && Number.isFinite(Number(km[1].replace(",", "."))))
      return { target: "journey", action: "seek_km", seek_km: Number(km[1].replace(",", ".")) };
    const phrase = text.replace(/^(?:voir|montre moi|montre|show me|show) /, "").replace(/^(?:la |le |les |the |l')/, "");
    for (const [chapter_id, phrases] of Object.entries(chapters)) {
      if (phrases.includes(phrase)) return { target: "journey", action: "show_chapter", chapter_id };
    }
    return null;
  }

  // The shell owns rendering, framing revision, and authenticated agent controls.
  function createVoiceInput(options = {}) {
    const getUserMedia = options.getUserMedia ?? globalThis.navigator?.mediaDevices?.getUserMedia?.bind(globalThis.navigator.mediaDevices);
    const Recorder = options.MediaRecorder ?? globalThis.MediaRecorder;
    const fetchAudio = options.fetch ?? globalThis.fetch;
    let snapshot = { state: "idle", textFallback: false, message: "" };
    let recorder, stream, completion, settle;
    const setState = (state, message = "") => {
      snapshot = { state, message, textFallback: ["permission_denied", "unsupported", "error"].includes(state) };
      options.onStateChange?.({ ...snapshot });
    };
    const release = () => { stream?.getTracks().forEach(track => track.stop()); stream = null; };
    const fail = error => { setState("error", error?.message || "Erreur microphone ou transcription"); settle?.(); };

    async function routeTranscript(text, revision) {
      const command = (options.parseCommand ?? parseJourneyCommand)(text);
      if (!command) {
        if (!Number.isInteger(revision)) throw new Error("Révision de cadrage absente");
        if (!options.onFramingReply) throw new Error("Cadrage vocal non connecté");
        await options.onFramingReply({ revision, text, channel: "voice" });
      } else if (command.target === "agents") {
        if (!options.onAgentsCommand) throw new Error("Contrôle des agents non connecté");
        await options.onAgentsCommand(command.action);
      } else {
        const method = { pause: "pause", play: "play", show_chapter: "showChapter", seek_km: "seekKm" }[command.action];
        if (!options.view?.[method]) throw new Error("Vue du séjour non connectée");
        await options.view[method](command.chapter_id ?? command.seek_km);
      }
    }

    async function start() {
      if (["requesting_permission", "listening", "transcribing"].includes(snapshot.state)) return false;
      if (!getUserMedia || !Recorder || !fetchAudio) { setState("unsupported", "Microphone non pris en charge ; utilisez le texte."); return false; }
      setState("requesting_permission");
      try {
        stream = await getUserMedia({ audio: true });
        recorder = new Recorder(stream);
        completion = new Promise(resolve => { settle = resolve; });
        const chunks = [];
        const revision = options.getRevision?.();
        recorder.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
        recorder.onerror = event => { release(); fail(event.error); };
        recorder.onstop = () => {
          release();
          if (snapshot.state === "error") return;
          setState("transcribing");
          (async () => {
            try {
              const audio = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "audio/webm" });
              if (!audio.size) throw new Error("Audio vide");
              const response = await fetchAudio("/api/transcribe", { method: "POST", headers: { "Content-Type": audio.type }, body: audio });
              if (!response.ok) {
                const detail = await response.text();
                throw new Error(`Transcription impossible (${response.status}) : ${detail}`);
              }
              const data = await response.json();
              if (typeof data.text !== "string" || !data.text.trim()) throw new Error("Transcription vide");
              if (data.text.length > 1000) throw new Error("Transcription trop longue pour le cadrage");
              await routeTranscript(data.text, revision);
              setState("idle");
            } catch (error) { fail(error); }
            finally { settle(); }
          })();
        };
        recorder.start();
        setState("listening");
        return true;
      } catch (error) {
        release();
        if (["NotAllowedError", "PermissionDeniedError"].includes(error.name)) setState("permission_denied", error.message || "Permission microphone refusée");
        else fail(error);
        return false;
      }
    }

    function stop() {
      if (snapshot.state !== "listening") return;
      try { recorder.stop(); } catch (error) { release(); fail(error); }
    }

    return { start, stop, getState: () => ({ ...snapshot }), whenSettled: () => completion };
  }

  return { parseJourneyCommand, createVoiceInput };
});
