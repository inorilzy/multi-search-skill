import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { createMeter, createAlertBadge } from '../ui/meter.js';

function setup(t) {
  const window = new Window();
  t.after(() => window.close());
  return window.document;
}

const progress = meter => meter.querySelector('[role="progressbar"]');

test('T05: remaining meter exposes percent, accessible values and the caller label', t => {
  const doc = setup(t);
  const meter = createMeter(doc, { remaining: 600, limit: 1000 }, { label: '个人账号剩余额度' });
  assert.equal(meter.querySelector('.meter-value').textContent, '60%');
  assert.equal(progress(meter).getAttribute('aria-label'), '个人账号剩余额度');
  assert.equal(progress(meter).getAttribute('aria-valuemin'), '0');
  assert.equal(progress(meter).getAttribute('aria-valuemax'), '100');
  assert.equal(progress(meter).getAttribute('aria-valuenow'), '60');
  assert.equal(progress(meter).getAttribute('aria-valuetext'), '60%');
  assert.equal(meter.querySelector('.meter-fill').style.width, '60%');
});

test('T05: strict low and critical thresholds include visible descriptions', t => {
  const doc = setup(t);
  for (const [percent, level, state] of [
    [100, 'normal', null], [20, 'normal', null], [19.99, 'low', '余额低'],
    [5, 'low', '余额低'], [4.99, 'critical', '余额即将用尽'], [0, 'critical', '余额即将用尽'],
  ]) {
    const meter = createMeter(doc, { percent });
    assert.equal(meter.dataset.level, level, `${percent}%`);
    assert.equal(meter.querySelector('.meter-state')?.textContent ?? null, state);
    if (state) assert.ok(progress(meter).getAttribute('aria-valuetext').includes(state));
  }
});

test('T05: relative meters show actual balance, the relative marker and historical percent', t => {
  const doc = setup(t);
  const meter = createMeter(doc, { remaining: 12.5, limit: null, percent: 25, relative: true, unit: 'usd' });
  assert.equal(meter.querySelector('.meter-value').textContent, '剩余 12.5 美元');
  assert.equal(meter.querySelector('.meter-relative').textContent, '相对');
  assert.equal(progress(meter).getAttribute('aria-valuenow'), '25');
  assert.match(progress(meter).getAttribute('aria-valuetext'), /剩余 12.5 美元（相对值 25%）/);
  assert.equal(meter.querySelector('.meter-empty'), null);
});

test('T05: no history, no upper bound and invalid data display text instead of empty bars', t => {
  const doc = setup(t);
  for (const total of [null, {}, { remaining: null, limit: 100 },
    { remaining: 12.5, limit: null, unit: 'usd' }, { remaining: 0, limit: 0 },
    { remaining: NaN, limit: 100 }, { percent: Infinity }, { percent: NaN }]) {
    const meter = createMeter(doc, total);
    assert.equal(progress(meter), null);
    assert.equal(meter.querySelector('.meter-empty').textContent, '暂无上限');
    assert.equal(meter.dataset.level, 'unknown');
    assert.doesNotMatch(meter.textContent, /NaN|Infinity/);
  }
  const meter = createMeter(doc, { remaining: 12.5, relative: true, unit: 'usd' });
  assert.match(meter.textContent, /剩余 12.5 美元相对暂无上限/);
  assert.equal(progress(meter), null);
});

test('T05: zero stays known, percentages clamp and supplied totals take precedence', t => {
  const doc = setup(t);
  for (const [total, value] of [
    [{ remaining: 0, limit: 100 }, 0], [{ remaining: -5, limit: 100 }, 0],
    [{ remaining: 200, limit: 100 }, 100], [{ percent: -10 }, 0], [{ percent: 125 }, 100],
    [{ remaining: 90, limit: 100, percent: 15 }, 15],
    [{ remaining: 50, limit: 100, percent: NaN }, 50],
  ]) {
    const meter = createMeter(doc, total);
    assert.equal(progress(meter).getAttribute('aria-valuenow'), String(value));
    assert.equal(meter.querySelector('.meter-fill').style.width, `${value}%`);
  }
});

test('T05: thin variant preserves the same information and accessibility', t => {
  const doc = setup(t);
  const meter = createMeter(doc, { percent: 40 }, { thin: true });
  assert.equal(meter.classList.contains('meter--thin'), true);
  assert.equal(progress(meter).getAttribute('aria-label'), '剩余额度');
  assert.equal(progress(meter).getAttribute('aria-valuenow'), '40');
  assert.equal(meter.querySelector('.meter-value').textContent, '40%');
});

test('T05: every reminder has explicit text and absent or unknown alerts render nothing', t => {
  const doc = setup(t);
  for (const [kind, text] of [
    ['low', '余额低'], ['critical', '余额即将用尽'],
    ['wont_last', '撑不到重置'], ['needs_credential', '需要凭据'],
  ]) {
    const badge = createAlertBadge(doc, kind);
    assert.equal(badge.textContent, text);
    assert.equal(badge.getAttribute('role'), 'status');
    assert.equal(badge.dataset.kind, kind);
  }
  for (const kind of [null, undefined, '', 'unknown', '__proto__', 'toString']) {
    assert.equal(createAlertBadge(doc, kind), null);
  }
});

test('T05: external unit, accessible label and alert message remain literal text', t => {
  const doc = setup(t);
  const hostile = '<img src=x onerror="alert(1)"><script>unsafe()</script>';
  const meter = createMeter(doc, { remaining: 2, percent: 40, relative: true, unit: hostile },
    { label: hostile });
  const badge = createAlertBadge(doc, 'needs_credential', hostile);
  doc.body.append(meter, badge);
  assert.equal(badge.textContent, hostile);
  assert.ok(meter.textContent.includes(hostile));
  assert.equal(progress(meter).getAttribute('aria-label'), hostile);
  assert.equal(doc.querySelector('img, script, [onerror]'), null);
});
