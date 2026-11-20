/** Document-wide input tracking shared by tooltip last-input and focus-ring policy. */
export const INPUT_MODALITY = { pointer: 'pointer', keyboard: 'keyboard' } as const;
export const INPUT_MODALITY_ATTRIBUTE = 'data-input-modality';

const FOCUS_NAVIGATION = new Set(['Tab', 'Home', 'End', 'PageUp', 'PageDown']);

let pointer = false;
let pointerOwnsFocus = false;
let keyFocusOrigin: EventTarget | undefined;

function publish(): void {
  document.documentElement.setAttribute(INPUT_MODALITY_ATTRIBUTE, pointerOwnsFocus ? INPUT_MODALITY.pointer : INPUT_MODALITY.keyboard);
}

/** Whether the last input came from a pointer, independently of focus-ring ownership. */
export function pointerModality(): boolean {
  return pointer;
}

if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', () => {
    pointer = true;
    pointerOwnsFocus = true;
    keyFocusOrigin = undefined;
    publish();
  }, true);
  window.addEventListener('keydown', (event) => {
    pointer = false;
    if (event.isComposing) {
      keyFocusOrigin = undefined;
      return;
    }
    keyFocusOrigin = event.composedPath()[0];
    if (!FOCUS_NAVIGATION.has(event.key) && !event.key.startsWith('Arrow')) return;
    pointerOwnsFocus = false;
    publish();
  }, true);
  window.addEventListener('focusin', (event) => {
    if (keyFocusOrigin === undefined || event.composedPath()[0] === keyFocusOrigin) return;
    keyFocusOrigin = undefined;
    if (!pointerOwnsFocus) return;
    pointerOwnsFocus = false;
    publish();
  }, true);
  window.addEventListener('blur', () => { keyFocusOrigin = undefined; });
}
