// @vitest-environment happy-dom
import { act, createRef } from 'react';
import type { ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Tip, TooltipProvider } from './Tooltip';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mounted: Array<{ container: HTMLDivElement; root: Root }> = [];
function mount(element: ReactNode) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted.push({ container, root });
  act(() => root.render(element));
  return { container, root };
}
afterEach(() => {
  for (const { container, root } of mounted.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  vi.useRealTimers();
});

describe('Tip', () => {
  it('resolves labels only while visible and renders shortcut keycaps with an accessible name', () => {
    const label = vi.fn(() => '保存');
    const { container } = mount(<TooltipProvider><Tip label={label} shortcutKeys={['Ctrl', '+', 'S']} maxWidth={160} openOnClick><button type="button">Save</button></Tip></TooltipProvider>);
    expect(label).not.toHaveBeenCalled();
    act(() => { container.querySelector('button')!.click(); });
    const tooltip = document.body.querySelector('[data-radix-popper-content-wrapper] .pop') as HTMLElement;
    expect(tooltip.textContent).toContain('保存');
    expect(Array.from(tooltip.querySelectorAll('kbd'), (node) => node.textContent)).toEqual(['Ctrl', 'S']);
    const descriptionId = container.querySelector('button')!.getAttribute('aria-describedby');
    expect(document.getElementById(descriptionId!)?.textContent).toBe('保存 Ctrl + S');
    expect(tooltip.style.maxWidth).toBe('160px');
  });

  it('uses a per-tip hover delay instead of the provider delay', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Delayed" delayMs={80}><button type="button">Hover</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { trigger.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
    act(() => { vi.advanceTimersByTime(79); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(document.body.querySelector('[role="tooltip"]')).not.toBeNull();
  });

  it('shows default hover immediately like the DSH tooltip', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Immediate"><button type="button">Immediate trigger</button></Tip></TooltipProvider>);
    act(() => { container.querySelector('button')!.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    act(() => { vi.advanceTimersByTime(0); });
    expect(document.body.querySelector('.pop')?.textContent).toContain('Immediate');
  });

  it('dismisses a hovered and focused bubble on anchor click without losing future hover', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Transient"><button type="button">Transient trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => { trigger.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    act(() => { vi.advanceTimersByTime(0); });
    expect(document.body.querySelector('.pop')).not.toBeNull();

    act(() => trigger.click());
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    act(() => trigger.dispatchEvent(new PointerEvent('pointerout', { bubbles: true, pointerType: 'mouse', relatedTarget: document.body })));
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => { trigger.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    act(() => { vi.advanceTimersByTime(0); });
    expect(document.body.querySelector('.pop')).not.toBeNull();
  });

  it('uses an independent delay for keyboard focus and cancels it on blur', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Keyboard help" focusDelayMs={80}><button type="button">Keyboard target</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => { vi.advanceTimersByTime(79); });
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(document.body.querySelector('.pop')?.textContent).toContain('Keyboard help');

    act(() => trigger.blur());
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('opens keyboard focus immediately and cancels a pending hover delay', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Mixed delay" delayMs={500} focusDelayMs={0}><button type="button">Mixed delay trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    const initialTimers = vi.getTimerCount();
    act(() => { trigger.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    expect(vi.getTimerCount()).toBe(initialTimers + 1);
    expect(document.body.querySelector('.pop')).toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => { vi.advanceTimersByTime(0); }); // flush Radix's zero-delay provider bookkeeping, not the hover wait
    expect(vi.getTimerCount()).toBe(initialTimers);
    act(() => trigger.blur());
    act(() => { vi.advanceTimersByTime(500); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('does not show focus-only help after pointer input', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Keyboard help" focusDelayMs={80}><button type="button">Pointer target</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'mouse' }));
    act(() => trigger.focus());
    act(() => { vi.advanceTimersByTime(80); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('can render within the trigger tree instead of the body portal', () => {
    const { container } = mount(<TooltipProvider><Tip label="Local bubble" openOnClick portal={false}><button type="button">Local trigger</button></Tip></TooltipProvider>);
    act(() => { container.querySelector('button')!.click(); });
    expect(container.querySelector('.pop')?.textContent).toContain('Local bubble');
  });

  it('preserves the anchor ref and chains its focus, blur, click, and mouse-leave handlers', () => {
    const ref = createRef<HTMLButtonElement>();
    const handlers = { focus: vi.fn(), blur: vi.fn(), click: vi.fn(), leave: vi.fn() };
    const { container } = mount(<TooltipProvider><Tip label="Composed" openOnClick><button ref={ref} onFocus={handlers.focus} onBlur={handlers.blur} onClick={handlers.click} onMouseLeave={handlers.leave}>Composed trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    expect(ref.current).toBe(trigger);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(handlers.focus).toHaveBeenCalledOnce();
    act(() => trigger.click());
    expect(handlers.click).toHaveBeenCalledOnce();
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    expect(handlers.leave).toHaveBeenCalledOnce();
    act(() => trigger.blur());
    expect(handlers.blur).toHaveBeenCalledOnce();
  });

  it.each(['click', 'disabled', 'unmount'] as const)('cancels pending keyboard focus on %s', (cancel) => {
    vi.useFakeTimers();
    const render = (disabled = false) => <TooltipProvider><Tip label="Pending" focusDelayMs={500} disabled={disabled}><button type="button">Pending trigger</button></Tip></TooltipProvider>;
    const { container, root } = mount(render());
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(vi.getTimerCount()).toBe(1);

    if (cancel === 'click') act(() => trigger.click());
    else if (cancel === 'disabled') act(() => root.render(render(true)));
    else act(() => root.render(null));

    expect(vi.getTimerCount()).toBe(0);
    act(() => { vi.advanceTimersByTime(500); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('cancels pending focus on mouse leave and withdraws an unpinned bubble while still focused', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Keyboard help" delayMs={0} focusDelayMs={80}><button type="button">Mixed input</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    act(() => { vi.advanceTimersByTime(40); });
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    act(() => { vi.advanceTimersByTime(80); });
    expect(document.body.querySelector('.pop')).toBeNull();

    act(() => trigger.blur());
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    act(() => { vi.advanceTimersByTime(80); });
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => trigger.blur());
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('suppresses a pinned parent while its nested tooltip is open and restores it afterward', () => {
    const { container } = mount(<TooltipProvider><Tip label="Outer details" openOnClick><div><Tip label="Inner details" openOnClick><button type="button">Inner hint</button></Tip></div></Tip></TooltipProvider>);
    const visiblePanels = () => Array.from(document.querySelectorAll<HTMLElement>('[data-radix-popper-content-wrapper] .pop'))
      .filter((panel) => panel.dataset.state === 'instant-open');
    const outerTrigger = container.querySelector('div')!;
    act(() => { outerTrigger.click(); });
    expect(visiblePanels()).toHaveLength(1);
    const innerTrigger = container.querySelector('button')!;
    act(() => { innerTrigger.click(); });
    expect(visiblePanels()).toHaveLength(1);
    expect(visiblePanels()[0].textContent).toContain('Inner details');
    act(() => { innerTrigger.click(); });
    expect(visiblePanels()).toHaveLength(1);
    expect(visiblePanels()[0].textContent).toContain('Outer details');
  });

  it('pins an informational tooltip on click and dismisses it with Escape, Tab, and outside pointer', () => {
    const { container } = mount(<TooltipProvider><Tip label="More information" openOnClick><button type="button">Info</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { trigger.click(); });
    const tooltip = document.body.querySelector('[role="tooltip"]');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain('More information');
    expect(trigger.getAttribute('aria-describedby')).toBeTruthy();
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => { trigger.click(); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
    act(() => { trigger.click(); });

    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
    act(() => { trigger.click(); });
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
    act(() => { trigger.click(); });
    act(() => { document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('consumes Escape while an unpinned focus tooltip is open, then lets it bubble', () => {
    const parentKeyDown = vi.fn();
    const { container } = mount(<TooltipProvider><div onKeyDown={parentKeyDown}><Tip label="Escape help"><button type="button">Escape target</button></Tip></div></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    act(() => trigger.focus());
    expect(document.body.querySelector('.pop')).not.toBeNull();

    const firstEscape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => trigger.dispatchEvent(firstEscape));
    expect(firstEscape.defaultPrevented).toBe(true);
    expect(parentKeyDown).not.toHaveBeenCalled();
    expect(document.body.querySelector('.pop')).toBeNull();

    const secondEscape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => trigger.dispatchEvent(secondEscape));
    expect(secondEscape.defaultPrevented).toBe(false);
    expect(parentKeyDown).toHaveBeenCalledOnce();
  });

  it('cancels delayed hover when click pins and prevents it reopening after Escape', () => {
    vi.useFakeTimers();
    const { container } = mount(<TooltipProvider><Tip label="Pinned info" openOnClick delayMs={300}><button type="button">Pin trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { trigger.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' })); });
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => trigger.click());
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => { vi.advanceTimersByTime(300); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it('suppresses an open hint immediately when disabled', () => {
    const render = (disabled: boolean) => <TooltipProvider><Tip label="More information" openOnClick disabled={disabled}><button type="button">Info</button></Tip></TooltipProvider>;
    const { container, root } = mount(render(false));
    act(() => { container.querySelector('button')!.click(); });
    expect(document.body.querySelector('[role="tooltip"]')).not.toBeNull();
    act(() => { root.render(render(true)); });
    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('clears a click pin when openOnClick is removed and allows pinning again', () => {
    const render = (openOnClick: boolean) => <TooltipProvider><Tip label="Remount-safe" openOnClick={openOnClick}><button type="button">Stable trigger</button></Tip></TooltipProvider>;
    const { container, root } = mount(render(true));
    const trigger = container.querySelector('button')!;
    act(() => trigger.click());
    expect(document.body.querySelector('.pop')).not.toBeNull();

    act(() => root.render(render(false)));
    expect(container.querySelector('button')).toBe(trigger);
    act(() => trigger.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })));
    expect(document.body.querySelector('.pop')).toBeNull();
    act(() => root.render(render(true)));
    expect(container.querySelector('button')).toBe(trigger);
    act(() => trigger.click());
    expect(document.body.querySelector('.pop')).not.toBeNull();
  });

  it('returns tooltip focus to keyboard modality after a composing key', () => {
    const { container } = mount(<TooltipProvider><Tip label="IME focus"><button type="button">IME trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { window.dispatchEvent(new Event('pointerdown')); });
    act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Process', bubbles: true, isComposing: true })); });
    act(() => { trigger.focus(); });
    expect(document.body.querySelector('[role="tooltip"]')).not.toBeNull();
  });

  it('dismisses a focus-open click-enabled tooltip on outside pointer input', () => {
    const { container } = mount(<TooltipProvider><Tip label="Outside dismiss" openOnClick><button type="button">Outside trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })); });
    act(() => { trigger.focus(); });
    expect(document.body.querySelector('.pop')).not.toBeNull();
    act(() => { document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });

  it.each([true, false])('keeps focus-open click-enabled content inside for outside pointer checks (portal=%s)', (portal) => {
    const { container } = mount(<TooltipProvider><Tip label="Inside dismiss" openOnClick portal={portal}><button type="button">Inside trigger</button></Tip></TooltipProvider>);
    const trigger = container.querySelector('button')!;
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })); });
    act(() => { trigger.focus(); });
    const bubble = document.body.querySelector('.pop')!;
    expect(bubble).not.toBeNull();
    act(() => { trigger.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); });
    expect(document.body.querySelector('.pop')).toBe(bubble);
    act(() => { bubble.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); });
    expect(document.body.querySelector('.pop')).toBe(bubble);
    act(() => { document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); });
    expect(document.body.querySelector('.pop')).toBeNull();
  });
});
