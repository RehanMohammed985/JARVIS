/** Chrome / Edge / Safari prefixed Web Speech API */

interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}

interface SpeechRecognitionResultList {
  readonly length: number;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
}

interface JarvisSpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((this: JarvisSpeechRecognition, ev: SpeechRecognitionEvent) => void) | null;
  onerror: ((this: JarvisSpeechRecognition, ev: SpeechRecognitionErrorEvent) => void) | null;
  onend: ((this: JarvisSpeechRecognition, ev: Event) => void) | null;
}

interface JarvisSpeechRecognitionConstructor {
  new (): JarvisSpeechRecognition;
}

interface Window {
  SpeechRecognition?: JarvisSpeechRecognitionConstructor;
  webkitSpeechRecognition?: JarvisSpeechRecognitionConstructor;
}
