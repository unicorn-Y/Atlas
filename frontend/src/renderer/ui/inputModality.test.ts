// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';
import { INPUT_MODALITY, INPUT_MODALITY_ATTRIBUTE, pointerModality } from './inputModality';

const press = (key: string, init: KeyboardEventInit = {}): void => {
  document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, composed: true, ...init }));
};
const click = (): void => { window.dispatchEvent(new Event('pointerdown')); };
const published = (): string | null => document.documentElement.getAttribute(INPUT_MODALITY_ATTRIBUTE);
const button = (): HTMLButtonElement => {
  const element = document.createElement('button');
  document.body.append(element);
  return element;
};

afterEach(() => {
  document.body.replaceChildren();
  window.dispatchEvent(new Event('blur'));
  press('Tab');
  document.documentElement.removeAttribute(INPUT_MODALITY_ATTRIBUTE);
});

describe('document input modality', () => {
  it('returns tooltip last-input mode to keyboard on every key', () => {
    for (const key of ['Shift', 'Escape', 'a', 'Enter', 'Tab']) {
      click();
      expect(pointerModality()).toBe(true);
      press(key);
      expect(pointerModality()).toBe(false);
    }
  });

  it('keeps a pointer-owned focus ring through keys that do not navigate', () => {
    click();
    for (const key of ['Shift', 'Escape', 'a', 'Control', 'Meta', 'Enter', ' ']) press(key);
    expect(published()).toBe(INPUT_MODALITY.pointer);
  });

  it('returns focus-ring ownership to keyboard on navigation keys', () => {
    for (const key of ['Tab', 'Home', 'End', 'PageUp', 'PageDown', 'ArrowDown', 'ArrowLeft']) {
      click();
      press(key);
      expect(published()).toBe(INPUT_MODALITY.keyboard);
    }
  });

  it.each(['Enter', ' ', 'Escape'])('switches focus-ring ownership when %s moves focus to another control', (key) => {
    const anchor = button();
    const destination = button();
    click();
    anchor.focus();
    press(key);
    expect(published()).toBe(INPUT_MODALITY.pointer);
    destination.focus();
    expect(document.activeElement).toBe(destination);
    expect(published()).toBe(INPUT_MODALITY.keyboard);
  });

  it('keeps keyboard modality when a navigation key moves focus', () => {
    click();
    button().focus();
    press('Tab');
    button().focus();
    expect(published()).toBe(INPUT_MODALITY.keyboard);
  });

  it('keeps pointer focus ownership when focus changes without a preceding key', () => {
    click();
    button().focus();
    expect(published()).toBe(INPUT_MODALITY.pointer);
  });

  it('does not treat refocusing the same control after Shift as navigation', () => {
    const target = button();
    click();
    target.focus();
    press('Shift');
    target.blur();
    target.focus();
    expect(published()).toBe(INPUT_MODALITY.pointer);
  });

  it('does not carry a pending key across a window blur', () => {
    click();
    button().focus();
    press('Meta');
    window.dispatchEvent(new Event('blur'));
    button().focus();
    expect(published()).toBe(INPUT_MODALITY.pointer);
  });

  it('does not interpret composing navigation as focus-ring navigation', () => {
    click();
    press('ArrowDown', { isComposing: true });
    expect(pointerModality()).toBe(false);
    expect(published()).toBe(INPUT_MODALITY.pointer);
    button().focus();
    expect(published()).toBe(INPUT_MODALITY.pointer);
  });
});
