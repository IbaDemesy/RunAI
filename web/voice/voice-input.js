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
    const Socket = options.WebSocket ?? globalThis.WebSocket;
    const Context = options.AudioContext ?? globalThis.AudioContext ?? globalThis.webkitAudioContext;
    const Worklet = options.AudioWorkletNode ?? globalThis.AudioWorkletNode;
    const fetchAudio = options.fetch ?? globalThis.fetch;
    const schedule = options.setTimeout ?? globalThis.setTimeout;
    const unschedule = options.clearTimeout ?? globalThis.clearTimeout;
    let snapshot = { state: "idle", textFallback: false, message: "" };
    let active, completion;
    const setState = (state, message = "") => {
      snapshot = { state, message, textFallback: ["permission_denied", "unsupported", "error"].includes(state) };
      options.onStateChange?.({ ...snapshot });
    };
    function releaseAudio(run) {
      if (run.processor?.port) run.processor.port.onmessage = null;
      if (run.processor) run.processor.onaudioprocess = null;
      for (const node of [run.source, run.processor, run.mute]) node?.disconnect();
      run.source = run.processor = run.mute = null;
      const context = run.context;
      run.context = null;
      if (context) Promise.resolve(context.close()).catch(() => {});
    }
    function releaseStream(run) {
      run.stream?.getTracks().forEach(track => track.stop());
      run.stream = null;
    }
    function closeSocket(run) {
      if (!run.socket) return;
      run.socket.onopen = run.socket.onmessage = run.socket.onerror = run.socket.onclose = null;
      if (run.socket.readyState < 2) run.socket.close();
      run.socket = null;
    }
    function finish(run, state, message = "") {
      if (run.done) return;
      run.done = true;
      for (const timer of [run.capTimer, run.readyTimer, run.endTimer]) unschedule(timer);
      releaseAudio(run);
      releaseStream(run);
      closeSocket(run);
      if (run.recorder?.state === "recording") {
        run.recorder.onstop = run.recorder.ondataavailable = run.recorder.onerror = null;
        run.recorder.stop();
      }
      setState(state, message);
      run.started(false);
      run.settle();
    }
    const fail = (run, error) => finish(run, "error", error?.message || "Microphone or transcription error");

    async function routeTranscript(text, revision) {
      const command = (options.parseCommand ?? parseJourneyCommand)(text);
      if (!command) {
        if (!Number.isInteger(revision)) throw new Error("Framing revision missing");
        if (!options.onFramingReply) throw new Error("Voice framing is not connected");
        await options.onFramingReply({ revision, text, channel: "voice" });
      } else if (command.target === "agents") {
        if (!options.onAgentsCommand) throw new Error("Agent controls are not connected");
        await options.onAgentsCommand(command.action);
      } else {
        const method = { pause: "pause", play: "play", show_chapter: "showChapter", seek_km: "seekKm" }[command.action];
        if (!options.view?.[method]) throw new Error("Journey view is not connected");
        await options.view[method](command.chapter_id ?? command.seek_km);
      }
    }

    async function deliver(run, text) {
      if (run.delivering || run.done) return;
      run.delivering = true;
      try {
        if (typeof text !== "string" || !text.trim()) throw new Error("No speech detected");
        if (text.length > 1000) throw new Error("Transcript too long for framing");
        await routeTranscript(text, run.revision);
        finish(run, "idle");
      } catch (error) { fail(run, error); }
    }

    function listening(run) {
      run.capTimer = schedule(() => stop(), 120000);
      setState("listening");
      run.started(true);
    }

    function uploadFallback(run) {
      if (run.done || run.fallback) return;
      run.fallback = true;
      unschedule(run.readyTimer);
      closeSocket(run);
      releaseAudio(run);
      if (!Recorder || !fetchAudio) {
        finish(run, "unsupported", "Microphone not supported; use text.");
        return;
      }
      try {
        const recorder = run.recorder = new Recorder(run.stream);
        const chunks = [];
        recorder.ondataavailable = event => { if (!run.done && event.data?.size) chunks.push(event.data); };
        recorder.onerror = event => fail(run, event.error);
        recorder.onstop = async () => {
          releaseStream(run);
          if (run.done) return;
          unschedule(run.capTimer);
          if (snapshot.state !== "transcribing") setState("transcribing");
          try {
            const audio = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "audio/webm" });
            if (!audio.size) throw new Error("No speech detected");
            const response = await fetchAudio("/api/transcribe", { method: "POST", headers: { "Content-Type": audio.type }, body: audio });
            if (!response.ok) throw new Error(`Transcription failed (${response.status})`);
            const data = await response.json();
            await deliver(run, data.text);
          } catch (error) { fail(run, error); }
        };
        recorder.start();
        listening(run);
      } catch (error) { fail(run, error); }
    }

    function send(run, data) {
      if (run.socket.bufferedAmount > 1024 * 1024) throw new Error("Voice connection is too slow; please try again");
      run.socket.send(data);
    }

    async function prepareAudio(run) {
      const context = run.context = new Context();
      await context.resume();
      if (run.done) return;
      run.encoder = pcmEncoder(context.sampleRate, frame => send(run, frame));
      run.source = context.createMediaStreamSource(run.stream);
      if (context.audioWorklet && Worklet) {
        await context.audioWorklet.addModule("/static/voice/pcm-worklet.js");
        if (run.done) return;
        run.processor = new Worklet(context, "runai-pcm", { channelCount: 1, channelCountMode: "explicit" });
        run.processor.port.onmessage = event => capture(event.data);
        run.processor.onprocessorerror = () => fail(run, new Error("Microphone audio processing failed"));
      } else {
        run.processor = context.createScriptProcessor(4096, 1, 1);
        run.processor.onaudioprocess = event => capture(event.inputBuffer.getChannelData(0));
      }
      run.mute = context.createGain();
      run.mute.gain.value = 0;
      run.processor.connect(run.mute);
      run.mute.connect(context.destination);
      function capture(samples) {
        if (!run.ready || run.stopping || run.done) return;
        try { run.encoder.push(samples); } catch (error) { fail(run, error); }
      }
    }

    function connect(run) {
      const location = options.location ?? globalThis.location;
      const protocol = location?.protocol === "https:" ? "wss:" : "ws:";
      run.socket = new Socket(`${protocol}//${location.host}/api/voice/stream`);
      run.socket.binaryType = "arraybuffer";
      run.readyTimer = schedule(() => uploadFallback(run), 8000);
      run.socket.onopen = () => {
        try { send(run, JSON.stringify({ type: "start", sample_rate: 16000 })); }
        catch (error) { uploadFallback(run); }
      };
      run.socket.onmessage = message => {
        if (run.done || run.delivering) return;
        try {
          const event = JSON.parse(message.data);
          if (event.type === "transcript") {
            if (!run.ready || typeof event.text !== "string") return;
            const id = event.utterance_id ?? "default";
            if (!run.finals.has(id)) run.finals.set(id, "");
            if (event.is_final) run.finals.set(id, event.text.trim());
            options.onPartial?.({ utterance_id: event.utterance_id, text: event.text, language: event.language, is_final: event.is_final });
            return;
          }
          options.onEvent?.(event);
          if (event.type === "ready" && !run.ready) {
            run.ready = true;
            unschedule(run.readyTimer);
            run.source.connect(run.processor);
            listening(run);
          } else if (event.type === "ended" && run.ready) {
            unschedule(run.endTimer);
            unschedule(run.capTimer);
            releaseAudio(run);
            releaseStream(run);
            if (snapshot.state !== "transcribing") setState("transcribing");
            void deliver(run, [...run.finals.values()].filter(Boolean).join(" "));
          } else if (event.type === "error") {
            if (!run.ready) uploadFallback(run);
            else fail(run, new Error("Voice transcription failed; please try again"));
          }
        } catch (error) {
          if (!run.ready) uploadFallback(run);
          else fail(run, error);
        }
      };
      run.socket.onerror = run.socket.onclose = () => {
        if (run.done || run.delivering) return;
        if (!run.ready) uploadFallback(run);
        else fail(run, new Error("Voice connection lost; please try again"));
      };
    }

    async function start() {
      if (["requesting_permission", "listening", "transcribing"].includes(snapshot.state)) return false;
      if (!getUserMedia || ((!Socket || !Context) && (!Recorder || !fetchAudio))) {
        setState("unsupported", "Microphone not supported; use text.");
        return false;
      }
      const run = active = { done: false, ready: false, finals: new Map() };
      completion = new Promise(resolve => { run.settle = resolve; });
      const started = new Promise(resolve => { run.started = resolve; });
      setState("requesting_permission");
      void (async () => {
        try {
          run.revision = options.getRevision?.();
          const stream = await getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
          if (run.done) { stream.getTracks().forEach(track => track.stop()); return; }
          run.stream = stream;
          if (!Socket || !Context) uploadFallback(run);
          else {
            try {
              await prepareAudio(run);
              if (!run.done) connect(run);
            } catch (error) { if (!run.done) uploadFallback(run); }
          }
        } catch (error) {
          if (!run.done) {
            if (["NotAllowedError", "PermissionDeniedError"].includes(error.name)) finish(run, "permission_denied", "Microphone permission denied");
            else fail(run, error);
          }
        }
      })();
      return started;
    }

    function stop() {
      const run = active;
      if (!run || run.done || run.stopping || run.delivering) return;
      if (snapshot.state === "requesting_permission") { finish(run, "idle"); return; }
      if (snapshot.state !== "listening") return;
      run.stopping = true;
      unschedule(run.capTimer);
      setState("transcribing");
      try {
        if (run.fallback) run.recorder.stop();
        else {
          releaseAudio(run);
          releaseStream(run);
          run.encoder.flush();
          send(run, JSON.stringify({ type: "stop" }));
          run.endTimer = schedule(() => fail(run, new Error("Voice transcription timed out; please try again")), 30000);
        }
      } catch (error) { fail(run, error); }
    }

    return { start, stop, getState: () => ({ ...snapshot }), whenSettled: () => completion };
  }

  // Keep fractional sample weights across input blocks, including 44.1 kHz input.
  function pcmEncoder(sampleRate, send) {
    if (!Number.isFinite(sampleRate) || sampleRate <= 0) throw new Error("Invalid microphone sample rate");
    const ratio = sampleRate / 16000;
    let sum = 0, weight = 0, frame = new ArrayBuffer(3200), size = 0;
    function emit(sample) {
      const value = Math.max(-1, Math.min(1, sample));
      new DataView(frame).setInt16(size * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
      if (++size === 1600) { send(frame); frame = new ArrayBuffer(3200); size = 0; }
    }
    return {
      push(samples) {
        for (const sample of samples) {
          let remaining = 1;
          while (remaining > 1e-9) {
            const take = Math.min(remaining, ratio - weight);
            sum += sample * take;
            weight += take;
            remaining -= take;
            if (weight >= ratio - 1e-9) { emit(sum / weight); sum = weight = 0; }
          }
        }
      },
      flush() {
        if (weight) { emit(sum / weight); sum = weight = 0; }
        if (size) { send(frame.slice(0, size * 2)); size = 0; }
      },
    };
  }

  return { parseJourneyCommand, createVoiceInput };
});
