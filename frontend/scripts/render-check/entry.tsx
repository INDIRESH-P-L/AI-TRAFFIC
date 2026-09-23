/**
 * Phase 3 component render check.
 *
 * Renders each new component to HTML with `renderToString`, using payloads
 * captured from the live backend, and asserts the truthfulness invariants
 * survive into the markup an operator would actually see.
 *
 * Typechecking and bundling prove none of this: a component can compile and
 * build cleanly and still throw on `undefined.map`, or - worse for this brief -
 * render a confident 0 where the API returned null.
 */

import { renderToString } from 'react-dom/server';
import { TrustPanel, TrustBadge } from '../../src/components/TrustPanel';
import { StringlineDiagram } from '../../src/components/StringlineDiagram';
import { VerificationPanel } from '../../src/components/VerificationPanel';
import { SnapshotView } from '../../src/pages/ShiftHandover';

import trustRated from './fixtures/trust_rated.json';
import trustUnrated from './fixtures/trust_unrated.json';
import stringline from './fixtures/stringline.json';
import verifyNoise from './fixtures/verify_noise.json';
import verifyImproved from './fixtures/verify_improved.json';
import verifyInsufficient from './fixtures/verify_insufficient.json';
import handover from './fixtures/handover.json';

let failures = 0;
let checks = 0;

function check(label: string, condition: boolean, detail = '') {
  checks += 1;
  if (!condition) {
    failures += 1;
    console.log('  FAIL  ' + label + (detail ? ' -- ' + detail : ''));
  } else {
    console.log('  ok    ' + label);
  }
}

function render(label: string, element: any): string {
  try {
    return renderToString(element);
  } catch (e: any) {
    failures += 1;
    checks += 1;
    console.log('  FAIL  ' + label + ' THREW: ' + (e?.message || e));
    return '';
  }
}

// Strip tags so text assertions are not fooled by attribute values.
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');

console.log('\n=== TrustPanel: UNRATED junction ===');
{
  const html = render('renders', <TrustPanel result={trustUnrated as any} />);
  const t = text(html);
  check('renders non-empty', html.length > 0);
  check('shows UNRATED band', t.includes('UNRATED'));
  check('score renders as a dash, not a number', t.includes('--'));
  check(
    'never prints a bare 0 as the score',
    !/>\s*0\s*<\/span>/.test(html),
    'a zero score would read as "measured and bad"',
  );
  // The explanation is the whole point of UNRATED: it must say on screen why
  // a dash is not a zero, in those terms.
  check('explains that zero would mean measured-and-bad', t.includes('measured and bad'));
  check('says nothing here has been measured', t.includes('nothing here has been measured'));
  check('lists what is not assessable', t.includes('Not assessable'));
  check('states the AI gate is closed', t.includes('WITHHELD'));
}

console.log('\n=== TrustPanel: rated junction ===');
{
  const html = render('renders', <TrustPanel result={trustRated as any} />);
  const t = text(html);
  const score = (trustRated as any).score;
  check('renders non-empty', html.length > 0);
  check('shows the composite score', t.includes(String(Math.round(score))));
  check('lists all five components', (trustRated as any).components.length === 5);
  for (const c of (trustRated as any).components) {
    check('component on screen: ' + c.name, t.includes(c.label));
  }
  check('shows the weight basis', t.includes('Renormalised'));
  check(
    'names the limiting factor',
    !(trustRated as any).weakest_component || t.includes('LIMITING FACTOR'),
  );
}

console.log('\n=== TrustBadge ===');
{
  const unrated = text(render('unrated badge', <TrustBadge band="UNRATED" score={null} />));
  check('unrated badge shows a dash', unrated.includes('--'));
  check('unrated badge does not show 0', !/\b0\b/.test(unrated));
  const trusted = text(render('trusted badge', <TrustBadge band="TRUSTED" score={88.2} />));
  check('trusted badge shows rounded score', trusted.includes('88'));
}

console.log('\n=== StringlineDiagram ===');
{
  const html = render('renders', <StringlineDiagram result={stringline as any} />);
  const t = text(html);
  check('renders non-empty', html.length > 0);
  check('emits an svg', html.includes('<svg'));

  const junctions = (stringline as any).junctions;
  for (const j of junctions) {
    check('track labelled: ' + j.name, t.includes(j.name.slice(0, 19)));
  }

  const totalBands = junctions.reduce((n: number, j: any) => n + j.bands.length, 0);
  const totalGaps = junctions.reduce((n: number, j: any) => n + j.gaps.length, 0);
  console.log('        (fixture has ' + totalBands + ' bands, ' + totalGaps + ' gaps)');

  check('defines the gap hatch pattern', html.includes('id="sl-gap"'));
  check(
    'gaps are painted with the hatch, not a colour',
    totalGaps === 0 || html.includes('url(#sl-gap)'),
    'an unobserved period must not render as a state',
  );
  check('legend explains the hatch', t.includes('No observations'));
  check('legend flags edge uncertainty', t.toLowerCase().includes('sampling uncertainty'));

  // The critical one: no progression line may be drawn for a segment the
  // backend refused to compute a speed for.
  const segments = (stringline as any).progression.segments;
  const computed = segments.filter((s: any) => s.status === 'COMPUTED');
  const dashedLines = (html.match(/stroke-dasharray="5 3"/g) || []).length;
  check(
    'progression lines drawn only for computed segments (' +
      computed.length + ' of ' + segments.length + ')',
    dashedLines <= computed.length,
    'drew ' + dashedLines + ' lines for ' + computed.length + ' computed segments',
  );
  for (const s of segments) {
    if (s.status !== 'COMPUTED') {
      check(
        'refused segment reports no speed: ' + s.status,
        s.implied_progression_speed_kph === null,
      );
    }
  }
}

console.log('\n=== VerificationPanel: noise ===');
{
  const html = render('renders', <VerificationPanel result={verifyNoise as any} />);
  const t = text(html);
  check('renders non-empty', html.length > 0);
  check('headline verdict is NO MEASURABLE CHANGE', t.includes('NO MEASURABLE CHANGE'));
  check('says the interval contains zero', t.includes('interval contains 0'));
  check('shows both interval bounds', t.includes('-1.71') && t.includes('1.31'));
  check('carries the method', t.includes('Welch'));
  check('carries the demand caveat', t.includes('Demand is not controlled for'));
  check('thin-sample metric is not given a verdict', t.includes('INSUFFICIENT DATA'));
}

console.log('\n=== VerificationPanel: real improvement ===');
{
  const html = render('renders', <VerificationPanel result={verifyImproved as any} />);
  const t = text(html);
  check('headline verdict is IMPROVED', t.includes('IMPROVED'));
  check('says the interval excludes zero', t.includes('interval excludes 0'));
  check('shows the difference', t.includes('-17.00') || t.includes('-17'));
}

console.log('\n=== VerificationPanel: insufficient data ===');
{
  const html = render('renders', <VerificationPanel result={verifyInsufficient as any} />);
  const t = text(html);
  check('renders non-empty', html.length > 0);
  check('shows INSUFFICIENT DATA', t.includes('INSUFFICIENT DATA'));
  check(
    'distinguishes unmeasured from no-effect',
    t.includes('not evidence the change had no effect'),
  );
  check('offers no verdict', !t.includes('IMPROVED') && !t.includes('DEGRADED'));
}

console.log('\n=== Handover snapshot ===');
{
  const snapshot = (handover as any).snapshot;
  const html = render('renders', <SnapshotView snapshot={snapshot} />);
  const t = text(html);
  check('renders non-empty', html.length > 0);

  const blind = snapshot.blind_spots;
  console.log('        (fixture: ' + blind.total_blind_count + ' unseen, ' +
    blind.partially_blind_count + ' partial, of ' + blind.total_junctions + ')');

  // The distinction added after finding the section cried wolf: a junction
  // polled all shift with no detectors is PARTIAL, not "we could not see it".
  check('headline separates unseen from partial', t.includes('UNSEEN') && t.includes('PARTIAL'));
  check('no longer labels every gap a blind spot', !t.includes('BLIND SPOTS -'));
  check('names the channels that did report', t.includes('Did report'));
  check(
    'a partially-covered junction says which channel reported',
    blind.partially_blind_count === 0 || t.includes('signal state'),
  );
  check('carries the why-this-matters text', t.includes('not observed at all'));

  const coverage = snapshot.data_coverage;
  check(
    'trust mean renders truthfully',
    coverage.network_trust_mean_of_rated === null
      ? t.includes('--')
      : t.includes(coverage.network_trust_mean_of_rated.toFixed(1)),
  );
  check('labels the mean as rated-only', t.includes('MEAN TRUST (RATED ONLY)'));
  check('shows the unrated count separately', t.includes('UNRATED'));
  check('reports safety engine rejections', t.includes('REJECTED BY SAFETY ENGINE'));
  check(
    'unprobed providers are not counted as working',
    !snapshot.providers.unprobed_note || t.includes('not the same as working'),
  );
}

console.log('\n=== Truthful empty states ===');
{
  // A snapshot that was generated but found nothing must still say so in
  // words. Rendering nothing at all is how "we did not look" gets mistaken
  // for "there was nothing to find".
  const emptySnapshot = {
    incidents: { open_count: 0, raised_this_shift: 0, resolved_this_shift: 0, items: [] },
    alerts: { unacknowledged_count: 0, escalated_count: 0, items: [] },
    providers: {
      total_known: 0, degraded_count: 0, unprobed_count: 0,
      degraded: [], unprobed_note: null,
    },
    signal_activity: {
      commands_issued: 0, commands_executed: 0,
      rejected_by_safety_engine: 0, rejection_reasons: [],
    },
    data_coverage: {
      network_trust_mean_of_rated: null, rated_junctions: 0,
      unrated_junctions: 0, by_band: {}, ai_gated_count: 0,
    },
    blind_spots: {
      count: 0, total_blind_count: 0, partially_blind_count: 0,
      total_junctions: 0, items: [],
      why_this_matters: '0 junction(s) were not observed at all this shift.',
    },
  };
  const t = text(render('empty snapshot', <SnapshotView snapshot={emptySnapshot} />));
  check('empty snapshot still renders', t.length > 0);
  check('a null trust mean renders as a dash, not 0.0', t.includes('--'));
  check('says every junction reported', t.includes('Every junction reported'));
  check('says no provider was degraded', t.includes('No provider was degraded'));

  const missing = text(render('absent snapshot', <SnapshotView snapshot={null} />));
  check('an absent snapshot says so explicitly', missing.includes('NO SNAPSHOT RECORDED'));

  // A stringline with no junctions must draw nothing rather than empty axes:
  // an empty diagram reads as "no green was displayed" when the truth is that
  // nothing was observed.
  const bare = render(
    'stringline with no junctions',
    <StringlineDiagram result={{ status: 'COMPUTED', junctions: [] } as any} />,
  );
  check('an empty stringline draws no axes at all', !bare.includes('<svg'));
}

console.log('\n' + '='.repeat(62));
console.log(checks + ' checks, ' + failures + ' failed');
if (failures > 0) process.exit(1);
console.log('ALL PHASE 3 COMPONENTS RENDER TRUTHFULLY');
