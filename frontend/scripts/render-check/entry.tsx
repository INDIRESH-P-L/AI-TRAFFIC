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
import { AnomalyPanel } from '../../src/components/intelligence/AnomalyPanel';
import { ForecastPanel } from '../../src/components/intelligence/ForecastPanel';
import { FusionPanel } from '../../src/components/intelligence/FusionPanel';
import anomalyMeasured from './fixtures/anomaly_measured.json';
import anomalyInsufficient from './fixtures/anomaly_insufficient.json';
import forecastAvailable from './fixtures/forecast_available.json';
import forecastNoSkill from './fixtures/forecast_no_skill.json';
import forecastNotComputable from './fixtures/forecast_not_computable.json';
import fusionProbable from './fixtures/fusion_probable.json';
import fusionUncorroborated from './fixtures/fusion_uncorroborated.json';
import { CoordinationPlanPanel, CoordinationVerifyPanel } from '../../src/components/coordination/CoordinationPlanPanel';
import { TspDecisionsPanel } from '../../src/components/transit/TspDecisionsPanel';
import { PreemptionVerdict } from '../../src/components/emergency/PreemptionVerdict';
import coordinationApplied from './fixtures/coordination_applied_live.json';
import coordinationVerify from './fixtures/coordination_verify_live.json';
import coordinationNotComputable from './fixtures/coordination_not_computable.json';
import coordinationRejected from './fixtures/coordination_rejected_by_safety.json';
import tspDryRun from './fixtures/tsp_dry_run.json';
import preemptionActive from './fixtures/preemption_active.json';
import preemptionRejected from './fixtures/preemption_rejected.json';
import preemptionFailed from './fixtures/preemption_failed.json';

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

console.log('\n=== AnomalyPanel: measured anomaly ===');
{
  const html = render('renders', <AnomalyPanel result={anomalyMeasured as any} />);
  const t = text(html);
  const flow = (anomalyMeasured as any).metrics.find((m: any) => m.metric === 'flow_rate_vph');
  check('headline is MEASURED ANOMALY', t.includes('MEASURED ANOMALY'));
  check('flagged value is on screen', t.includes(String(flow.flagged_points[0].value)));
  check('flag names its source row', t.includes('traffic_metrics#'));
  check('confidence never rounds up to 100%', !t.includes('100.00%'));
  check('unrecorded metric is listed as not evaluated', t.includes('NOT EVALUATED'));
  check('unrecorded metric says NOT COMPUTABLE with its reason',
    t.includes('NOT COMPUTABLE') && t.includes('NO_STORED_VALUES_FOR_METRIC'));
  check('states that no flag is not evidence of normal', t.includes('not evidence of normal conditions'));
  check('fallback baseline caveat is visible', t.includes('does not account for the daily pattern'));
}

console.log('\n=== AnomalyPanel: insufficient baseline ===');
{
  const t = text(render('renders', <AnomalyPanel result={anomalyInsufficient as any} />));
  check('says INSUFFICIENT DATA', t.includes('INSUFFICIENT DATA'));
  check('names the reason', t.includes('BASELINE_TOO_SMALL'));
  check('never renders MEASURED ANOMALY', !t.includes('MEASURED ANOMALY'));
  check('shows candidate counts against the requirement', t.includes('required: 30'));
}

console.log('\n=== ForecastPanel: forecast available ===');
{
  const html = render('renders', <ForecastPanel result={forecastAvailable as any} />);
  const t = text(html);
  check('stamped SCENARIO / HYPOTHETICAL', t.includes('SCENARIO / HYPOTHETICAL'));
  check('says model forecast, not observed', t.includes('NOT OBSERVED'));
  check('draws the forecast as a distinct dashed series', html.includes('data-kind="MODEL_FORECAST"'));
  check('labels the measured side of the chart', t.includes('MEASURED'));
  check('shows the fitted order', t.includes((forecastAvailable as any).model.order));
  check('shows persistence MAE beside model MAE', t.includes('PERSISTENCE MAE'));
  check('shows measured interval coverage', t.includes('MEASURED 95% COVERAGE'));
  check('names the model as having no MA terms', t.includes('no moving-average terms'));
}

console.log('\n=== ForecastPanel: refused for lack of skill ===');
{
  const html = render('renders', <ForecastPanel result={forecastNoSkill as any} />);
  const t = text(html);
  check('says INSUFFICIENT DATA FOR RELIABLE FORECAST', t.includes('INSUFFICIENT DATA FOR RELIABLE FORECAST'));
  check('names the refusal reason', t.includes('NO_SKILL_OVER_PERSISTENCE'));
  check('the refusal shows the model behind it', t.includes('A MODEL WAS FITTED AND MEASURED'));
  check('no forecast line is drawn', !html.includes('data-kind="MODEL_FORECAST"'));
  check('says no line is drawn for a refusal', t.includes('No forecast line is drawn'));
  check('not stamped as an available scenario', !t.includes('MODEL FORECAST, NOT OBSERVED DATA'));
}

console.log('\n=== ForecastPanel: metric never recorded ===');
{
  const html = render('renders', <ForecastPanel result={forecastNotComputable as any} />);
  const t = text(html);
  check('says NOT COMPUTABLE', t.includes('NOT COMPUTABLE'));
  check('explains waiting will not help', t.includes('Waiting will not help'));
  // Matched on the chart's own label: the status icon is also an SVG.
  check('draws no chart at all', !html.includes('Observed bins followed by model forecast'));
}

console.log('\n=== FusionPanel: corroborated probable incident ===');
{
  const html = render('renders', <FusionPanel result={fusionProbable as any} onRecord={() => undefined} />);
  const t = text(html);
  check('headline is PROBABLE INCIDENT', t.includes('PROBABLE INCIDENT'));
  check('names both corroborating sources', t.includes('nb-loop-1') && t.includes('nb-radar-2'));
  check('record action says it files DETECTED', t.includes('Record as DETECTED'));
  check('record action says it verifies nothing', t.includes('does not verify anything'));
  check('single-sensor segment is NOT COMPUTABLE', t.includes('FEWER_THAN_TWO_INDEPENDENT_SOURCES'));
  check('lane-less source is reported, not placed', t.includes('UNATTRIBUTED SOURCES') && t.includes('roaming-probe'));
  check('ratio is not presented as a probability', t.includes('not a probability'));
}

console.log('\n=== FusionPanel: one detector agreeing with itself ===');
{
  const t = text(render('renders', <FusionPanel result={fusionUncorroborated as any} onRecord={() => undefined} />));
  check('segment is UNCORROBORATED SINGLE SOURCE', t.includes('UNCORROBORATED SINGLE SOURCE'));
  check('names the dissenting source', t.includes('Evaluated, no symptom') && t.includes('nb-radar-2'));
  check('offers no record action', !t.includes('Record as DETECTED'));
}

console.log('\n=== CoordinationPlanPanel: applied on a live corridor ===');
{
  const html = render('renders', <CoordinationPlanPanel plan={coordinationApplied as any} />);
  const t = text(html);
  check('says every controller applied', t.includes('APPLIED TO EVERY CONTROLLER'));
  check('design speed is labelled not measured', t.includes('NOT MEASURED'));
  check('names the cycle basis', t.includes((coordinationApplied as any).cycle_basis));
  check('the diagram is labelled PLANNED, not observed', t.includes('(NOT OBSERVED)'));
  check('planned windows are drawn as planned', html.includes('data-kind="PLANNED"'));
  check('reports the opposite-direction band too', t.includes('OPPOSITE-DIRECTION BAND'));
  check('every controller shows its read-back', t.includes('read-back matches'));
  check('carries the clock-sync caveat', t.includes('cannot verify controller clock sync'));
  check('never claims the wave works without verification', !t.includes('WORKING'));
}

console.log('\n=== CoordinationVerifyPanel: observed by the stringline ===');
{
  const t = text(render('renders', <CoordinationVerifyPanel result={coordinationVerify as any} />));
  const segment = (coordinationVerify as any).segments[0];
  check('headline is OBSERVED AS PLANNED', t.includes('OBSERVED AS PLANNED'));
  check('shows planned beside observed', t.includes(`${segment.planned_offset_sec}s`) && t.includes(String(segment.observed_median_offset_sec)));
  check('shows the tolerance used', t.includes('tol'));
  check('states the observation basis', t.includes('measured by the stringline'));
}

console.log('\n=== CoordinationPlanPanel: refusals ===');
{
  const t = text(render('renders', <CoordinationPlanPanel plan={coordinationNotComputable as any} />));
  check('says NOT COMPUTABLE', t.includes('NOT COMPUTABLE'));
  check('names the refusal', t.includes('FEWER_THAN_TWO_COORDINATABLE_CONTROLLERS'));
  check('lists why each junction cannot be coordinated',
    t.includes('NO_CONTROLLER') && t.includes('PROTOCOL_HAS_NO_TIMING_PLAN_CHANNEL'));

  const r = text(render('renders', <CoordinationPlanPanel plan={coordinationRejected as any} />));
  check('rejected plan says REJECTED BY SAFETY ENGINE', r.includes('REJECTED BY SAFETY ENGINE'));
  check('names the violated rule', r.includes('configured as conflicting'));
  check('rejected plan shows no applied column', !r.includes('read-back'));
}

console.log('\n=== TspDecisionsPanel: dry run ===');
{
  const t = text(render('renders', <TspDecisionsPanel result={tspDryRun as any} />));
  check('labelled as a dry run that sent nothing', t.includes('NOTHING SENT, NOTHING RECORDED'));
  check('shows the would-request decision', t.includes('WOULD REQUEST GREEN EXTENSION'));
  check('shows the on-time refusal with its reason', t.includes('NOT LATE ENOUGH'));
  check('unknown lateness is shown as UNKNOWN, not 0', t.includes('UNKNOWN') && t.includes('NO SCHEDULE ADHERENCE DATA'));
  check('a bus not near a junction is still listed', t.includes('BUS-FAR'));
  check('states early green is not requested', t.includes('force-off'));
}

console.log('\n=== PreemptionVerdict ===');
{
  const active = text(render('active', <PreemptionVerdict verdict={preemptionActive as any} />));
  check('active says the controller acknowledged', active.includes('CONTROLLER ACKNOWLEDGED'));

  const failed = text(render('failed', <PreemptionVerdict verdict={preemptionFailed as any} />));
  check('failed says the controller did not acknowledge', failed.includes('DID NOT ACKNOWLEDGE'));
  check('failed says no preemption is in effect', failed.includes('NO PREEMPTION IS IN EFFECT'));
  check('failed is never rendered as granted or active',
    !failed.includes('GRANTED') && !failed.includes('PREEMPTION ACTIVE'));

  const rejected = text(render('rejected', <PreemptionVerdict verdict={preemptionRejected as any} />));
  check('rejected says nothing was sent', rejected.includes('NOTHING WAS SENT'));
  check('rejected lists the violation', rejected.includes('conflicts with active Phase'));
}

console.log('\n' + '='.repeat(62));
console.log(checks + ' checks, ' + failures + ' failed');
if (failures > 0) process.exit(1);
console.log('ALL CHECKED COMPONENTS RENDER TRUTHFULLY');
