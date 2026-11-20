import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import DateTimePicker, { computeAnchoredPosition, isInsidePopover } from './DateTimePicker';

describe('DateTimePicker', () => {
  it('clamps anchored panels on all viewport edges and honors side/alignment', () => {
    expect(computeAnchoredPosition(
      { left: 260, right: 300, top: 170, bottom: 190 }, { width: 120, height: 80 }, { width: 320, height: 220 },
      { side: 'bottom', align: 'end', gap: 4, margin: 12 },
    )).toEqual({ left: 180, top: 128 });
    expect(computeAnchoredPosition(
      { left: 4, right: 44, top: 60, bottom: 80 }, { width: 90, height: 50 }, { width: 320, height: 220 },
      { side: 'top', align: 'start', gap: 4, margin: 12 },
    )).toEqual({ left: 12, top: 12 });
    expect(computeAnchoredPosition(
      { left: 0, right: 20, top: 0, bottom: 10 }, { width: 400, height: 300 }, { width: 320, height: 220 },
      { side: 'bottom', align: 'start', gap: 4, margin: 12 },
    )).toEqual({ left: 12, top: 12 });
  });

  it('treats the trigger and portaled panel as inside pointer targets', () => {
    const root = { contains: (target: unknown) => target === 'trigger' };
    const panel = { contains: (target: unknown) => target === 'panel' };
    expect(isInsidePopover('trigger', root, panel)).toBe(true);
    expect(isInsidePopover('panel', root, panel)).toBe(true);
    expect(isInsidePopover('outside', root, panel)).toBe(false);
    expect(isInsidePopover(null, root, panel)).toBe(false);
  });

  it('navigates Monday-first calendar months and writes a local ISO date-time', () => {
    const Harness = () => {
      const [value, setValue] = useState('2026-11-18T09:30');
      return <><DateTimePicker label="运行时间" value={value} onChange={setValue} /><output>{value}</output></>;
    };
    let view: ReactTestRenderer;
    act(() => {
      view = create(<Harness />);
    });

    const findButton = (name: string) => view!.root.find((node) => node.type === 'button' && node.props['aria-label'] === name);
    act(() => { findButton('选择运行时间').props.onClick(); });
    expect(view!.root.findByProps({ role: 'grid' })).toBeTruthy();
    expect(view!.root.findAllByProps({ role: 'columnheader' }).map((node) => node.children.join(''))).toEqual(['一', '二', '三', '四', '五', '六', '日']);

    act(() => { findButton('下个月').props.onClick(); });
    expect(view!.root.findByProps({ 'data-calendar-month': '2026-12' })).toBeTruthy();
    act(() => { findButton('选择日期 2026-12-05').props.onClick(); });
    expect(view!.root.findByType('output').children.join('')).toBe('2026-12-05T09:30');

    const hour = view!.root.find((node) => node.type === 'button' && node.props['aria-label'] === '17点');
    act(() => { hour.props.onClick(); });
    expect(view!.root.findByType('output').children.join('')).toBe('2026-12-05T17:30');
    const minute = view!.root.find((node) => node.type === 'button' && node.props['aria-label'] === '45分');
    act(() => { minute.props.onClick(); });
    expect(view!.root.findByType('output').children.join('')).toBe('2026-12-05T17:45');
    act(() => { view!.unmount(); });
  });

  it('keeps an empty value until a date is selected and initializes its time to midnight', () => {
    const Harness = () => {
      const [value, setValue] = useState('');
      return <><DateTimePicker label="运行时间" value={value} onChange={setValue} /><output>{value}</output></>;
    };
    let view: ReactTestRenderer;
    act(() => {
      view = create(<Harness />);
    });
    const findButton = (name: string) => view!.root.find((node) => node.type === 'button' && node.props['aria-label'] === name);
    act(() => { findButton('选择运行时间').props.onClick(); });
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    act(() => { findButton(`选择日期 ${iso}`).props.onClick(); });
    expect(view!.root.findByType('output').children.join('')).toBe(`${iso}T00:00`);
    act(() => { view!.unmount(); });
  });

  it('supports calendar keyboard movement and closes on Escape while preserving required form state', () => {
    let view: ReactTestRenderer;
    act(() => {
      view = create(<DateTimePicker label="时刻" value="" required onChange={() => undefined} />);
    });
    const findButton = (name: string) => view!.root.find((node) => node.type === 'button' && node.props['aria-label'] === name);
    act(() => { findButton('选择时刻').props.onClick(); });
    const today = new Date();
    const day = today.getDate();
    const current = findButton(`选择日期 ${`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`}`);
    act(() => { current.props.onKeyDown({ key: 'ArrowDown', preventDefault() {} }); });
    const nextWeek = findButton(`选择日期 ${`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(Math.min(day + 7, new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate())).padStart(2, '0')}`}`);
    expect(nextWeek.props.tabIndex).toBe(0);
    expect(view!.root.find((node) => node.type === 'input' && node.props.type === 'datetime-local').props.required).toBe(true);
    act(() => { nextWeek.props.onKeyDown({ key: 'Escape', preventDefault() {} }); });
    expect(findButton('选择时刻').props['aria-expanded']).toBe(false);
    act(() => { view!.unmount(); });
  });
});
