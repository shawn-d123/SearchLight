// Live transcription for the intake screen.
//
// Browser Web Speech API, not Whisper. It transcribes word by word with no
// upload and no round trip, which is the whole effect -- Whisper needs
// record, upload, wait, which kills it.
//
// TWO HONEST RULES, both of which the demo depends on:
//
//   1. `mode` is always visible to the caller. When the fallback is running,
//      mode === "recorded". NEVER render a recorded replay as if it were live.
//      A scripted typewriter presented as live transcription is the easiest
//      thing in this demo for a judge to catch, because they will ask to speak
//      into the microphone themselves.
//   2. The transcript is texture; the extraction is the hero. The room will be
//      loud and recognition WILL mangle words. That is fine and it is worth
//      saying out loud when it happens -- verified: "marshal gulch" with one L
//      still resolves to the right trailhead, because the server matches place
//      names against a gazetteer rather than trusting the model.
//
// Chrome and Edge only. Firefox and Safari do not implement SpeechRecognition,
// so `supported` will be false there and the fallback is the only path.
// Requires https:// or localhost.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

export type TranscriptionMode = "idle" | "live" | "recorded";

// The Web Speech API has no lib.dom types in this TS version, so the surface
// this hook actually touches is declared here. Narrow on purpose: an `any`
// would hide a rename in the two event shapes below, which are the only place
// live words enter the application.
interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  readonly length: number;
  readonly isFinal: boolean;
  [index: number]: RecognitionAlternative;
}
interface RecognitionResultList {
  readonly length: number;
  [index: number]: RecognitionResult;
}
interface RecognitionResultEvent {
  resultIndex: number;
  results: RecognitionResultList;
}
interface RecognitionErrorEvent {
  error?: string;
}

type Recognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: RecognitionResultEvent) => void) | null;
  onerror: ((e: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
};

type RecognitionConstructor = new () => Recognition;

function getRecognition(): Recognition | null {
  if (typeof window === "undefined") return null;
  const w = window as typeof window & {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function isTranscriptionSupported(): boolean {
  return getRecognition() !== null;
}

/** Support never changes after load, so nothing ever needs to subscribe. */
const subscribeNever = () => () => {};

/** Types `text` out at a believable speaking pace. ~150 wpm. */
function replay(
  text: string,
  onChunk: (soFar: string) => void,
  done: () => void,
  wordsPerMinute = 150,
) {
  const words = text.split(/\s+/);
  const delay = 60000 / wordsPerMinute;
  let i = 0;
  const timer = setInterval(() => {
    i += 1;
    onChunk(words.slice(0, i).join(" "));
    if (i >= words.length) {
      clearInterval(timer);
      done();
    }
  }, delay);
  return () => clearInterval(timer);
}

export type UseTranscription = {
  /** Everything heard so far, interim words included. */
  transcript: string;
  /** "live" = microphone. "recorded" = fallback. SHOW THIS DIFFERENCE. */
  mode: TranscriptionMode;
  listening: boolean;
  supported: boolean;
  error: string | null;
  startLive: () => void;
  startRecorded: () => void;
  stop: () => void;
};

/**
 * @param send  called with each CONTRACT.md `transcript_partial` payload;
 *              wire it to the WebSocket. The server extracts on is_final.
 */
export function useTranscription(
  send: (payload: { text: string; is_final: boolean }) => void,
  fallbackUrl = "/mocks/transcript.txt",
): UseTranscription {
  const [transcript, setTranscript] = useState("");
  const [mode, setMode] = useState<TranscriptionMode>("idle");
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Read through useSyncExternalStore rather than set from an effect: the
  // server has no SpeechRecognition, so it renders the unsupported branch
  // and the client corrects it on hydration with no intermediate paint.
  const supported = useSyncExternalStore(
    subscribeNever,
    isTranscriptionSupported,
    () => false,
  );

  const recRef = useRef<Recognition | null>(null);
  const cancelReplay = useRef<null | (() => void)>(null);
  const finalRef = useRef("");

  const stop = useCallback(() => {
    cancelReplay.current?.();
    cancelReplay.current = null;
    try {
      recRef.current?.stop();
    } catch {
      /* already stopped */
    }
    recRef.current = null;
    setListening(false);
  }, []);

  const startLive = useCallback(() => {
    const rec = getRecognition();
    if (!rec) {
      setError("This browser has no SpeechRecognition. Use Chrome or Edge.");
      return;
    }
    finalRef.current = "";
    setTranscript("");
    setError(null);
    setMode("live");
    setListening(true);

    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-GB";

    rec.onresult = (e: RecognitionResultEvent) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalRef.current += chunk + " ";
        else interim += chunk;
      }
      const text = (finalRef.current + interim).trim();
      setTranscript(text);
      // Interim words keep every client in sync with the call as it is spoken.
      // The server only spends an extraction call on is_final.
      send({ text, is_final: false });
    };

    rec.onerror = (e: RecognitionErrorEvent) => {
      // "no-speech" and "aborted" are normal and not worth showing.
      if (e?.error && e.error !== "no-speech" && e.error !== "aborted") {
        setError(String(e.error));
      }
    };

    rec.onend = () => {
      setListening(false);
      const text = finalRef.current.trim();
      if (text) send({ text, is_final: true });
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch (err) {
      setError(String(err));
      setListening(false);
    }
  }, [send]);

  const startRecorded = useCallback(() => {
    stop();
    setError(null);
    setMode("recorded"); // the UI MUST show this differently from "live"
    setListening(true);
    setTranscript("");

    fetch(fallbackUrl)
      .then((r) => r.text())
      .then((text) => {
        cancelReplay.current = replay(
          text,
          (soFar) => {
            setTranscript(soFar);
            send({ text: soFar, is_final: false });
          },
          () => {
            setListening(false);
            send({ text, is_final: true });
          },
        );
      })
      .catch((e) => {
        setError("could not load " + fallbackUrl + ": " + e);
        setListening(false);
      });
  }, [fallbackUrl, send, stop]);

  useEffect(() => stop, [stop]);

  return {
    transcript,
    mode,
    listening,
    supported,
    error,
    startLive,
    startRecorded,
    stop,
  };
}
