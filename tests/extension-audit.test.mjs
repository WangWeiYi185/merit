import assert from 'node:assert/strict';
import { createRequire, registerHooks } from 'node:module';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { pathToFileURL, fileURLToPath } from 'node:url';
import test from 'node:test';

const host = process.env.PI_CODING_AGENT_DIR;
const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
let factory, visibleWidth;
if (host) {
  const require = createRequire(join(host, 'package.json'));
  const aliases = new Map(['typebox', '@earendil-works/pi-tui']
    .map(name => [name, pathToFileURL(require.resolve(name)).href]));
  const metadata = JSON.parse(await readFile(join(host, 'package.json'), 'utf8'));
  aliases.set('@earendil-works/pi-coding-agent', pathToFileURL(join(host, metadata.exports['.'].import)).href);
  registerHooks({ resolve(specifier, context, next) {
    return next(aliases.get(specifier) ?? specifier, context);
  }});
  factory = (await import('../extensions/ai-workflow-audit.ts')).default;
  visibleWidth = (await import('@earendil-works/pi-tui')).visibleWidth;
}

async function fixture(t) {
  const cwd = await mkdtemp(join(tmpdir(), 'workflow-extension-'));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const git = spawnSync('git', ['init', '-q'], { cwd, encoding: 'utf8' });
  assert.equal(git.status, 0, git.stderr);
  const flow = (...args) => {
    const result = spawnSync('python3', [join(root, 'workflow.py'), ...args], { cwd, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout;
  };
  for (const name of ['one', 'two']) {
    flow('init', name, '--goal', '测试节点');
    flow('add', name, 'T01', '--title', '实际任务', '--investigation');
  }
  const handlers = new Map(), tools = new Map(), commands = new Map(), entries = [];
  const notices = [], screens = [], selections = [], registered = [];
  let closed = false;
  const pi = {
    on(name, handler) { handlers.set(name, handler); },
    registerTool(tool) { tools.set(tool.name, tool); },
    registerCommand(name, command) { commands.set(name, command); },
    appendEntry(customType, data) {
      assert.ok(!closed, 'old session API must not be used after shutdown');
      entries.push({ type: 'custom', customType, data });
    },
    getCommands() { return registered; },
  };
  const ctx = {
    cwd, mode: 'tui', hasUI: true,
    sessionManager: { getBranch: () => entries, getSessionId: () => 'session-fixture' },
    ui: {
      notify(text, type) { notices.push({ text, type }); },
      setStatus(key, text) { if (text) notices.push({ text, type: key }); },
      setEditorText(text) { notices.push({ text, type: 'editor' }); },
      async select(_title, options) {
        const desired = selections.shift();
        return desired === undefined ? undefined : options.find(option => option.includes(desired));
      },
      async custom(build) {
        const component = await build({ terminal: { rows: 20 }, requestRender() {} },
          { fg: (_kind, text) => text, bold: text => text },
          { matches: (key, id) => key === 'escape' && id === 'tui.select.cancel' || key === 'down' && id === 'tui.select.down' }, () => {});
        for (const width of [18, 80]) {
          const lines = component.render(width);
          assert.ok(lines.every(line => visibleWidth(line) <= width), 'UI must fit narrow terminals');
          screens.push(lines.join('\n'));
          for (let step = 0; step < 100; step++) {
            component.handleInput?.('down');
            const page = component.render(width);
            assert.ok(page.every(line => visibleWidth(line) <= width));
            screens.push(page.join('\n'));
          }
        }
        component.handleInput?.('escape');
      },
    },
  };
  factory(pi);
  const emit = async (name, event = {}) => {
    if (name === 'session_start') closed = false;
    const result = await handlers.get(name)?.(event, ctx);
    if (name === 'session_shutdown') closed = true;
    return result;
  };
  const scope = async (requirement, extra = {}) => tools.get('ai_workflow_audit_context').execute('scope',
    { requirement, task: 'T01', stage: 'execute', ...extra }, undefined, undefined, ctx);
  const events = async requirement => {
    try { return (await readFile(join(cwd, '.ai-workflow', requirement, 'audit/events.jsonl'), 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  };
  return { cwd, flow, pi, ctx, emit, scope, events, tools, commands, entries, notices, screens, selections, registered };
}

const options = { skip: !host && 'Set PI_CODING_AGENT_DIR to installed Pi package for extension integration tests' };

test('parallel tool results keep the scope captured when each call started', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('tool_execution_start', { toolCallId: 'call-one', toolName: 'read', args: { path: 'app.swift', offset: 4, limit: 2 } });
  await f.scope('two');
  await f.emit('tool_execution_end', { toolCallId: 'call-one', toolName: 'read', args: { path: 'app.swift', offset: 4, limit: 2 },
    result: { content: [{ type: 'text', text: 'observed source snippet' }], details: {} }, isError: false });
  const one = await f.events('one'), two = await f.events('two');
  assert.ok(one.some(event => event.node === 'call-one'));
  assert.ok(!two.some(event => event.node === 'call-one'));
  const original = JSON.parse(f.flow('evidence', 'one', one.find(event => event.node === 'call-one').evidence, '--json'));
  assert.equal(original.input.offset, 4);
  assert.equal(original.output.content[0].text, 'observed source snippet');
});

test('loaded rules preserve actual prompt contents rather than rereading changed files', options, async t => {
  const f = await fixture(t);
  const path = join(f.cwd, 'AGENTS.md');
  await writeFile(path, 'new disk rule');
  await f.emit('before_agent_start', { messageType: 'user', prompt: '保留全部组件',
    systemPromptOptions: { contextFiles: [{ path, content: 'old actually loaded rule' }] } });
  await f.scope('one');
  const event = (await f.events('one')).find(entry => entry.kind === 'rule');
  assert.ok(event);
  const evidence = JSON.parse(f.flow('evidence', 'one', event.evidence, '--json'));
  assert.equal(evidence.content, 'old actually loaded rule');
  assert.ok(!JSON.stringify(evidence).includes('new disk rule'));
  await f.emit('tool_execution_start', { toolCallId: 'partial-rule', toolName: 'read', args: { path, offset: 4, limit: 1 } });
  await f.emit('tool_result', { toolCallId: 'partial-rule', toolName: 'read', input: { path, offset: 4, limit: 1 } });
  await f.emit('tool_execution_end', { toolCallId: 'partial-rule', toolName: 'read', result: { content: [{ type: 'text', text: 'partial rule line' }] }, isError: false });
  const partial = JSON.parse(f.flow('board', 'one', 'T01', '--json'));
  assert.ok(!partial.warnings.some(warning => warning.includes('版本不一致')));
  await f.emit('tool_execution_start', { toolCallId: 'new-rule', toolName: 'read', args: { path } });
  await f.emit('tool_result', { toolCallId: 'new-rule', toolName: 'read', input: { path } });
  await f.emit('tool_execution_end', { toolCallId: 'new-rule', toolName: 'read', result: {
    content: [{ type: 'text', text: 'new disk rule' }] }, isError: false });
  const changed = JSON.parse(f.flow('board', 'one', 'T01', '--json'));
  assert.ok(changed.warnings.some(warning => warning.includes('版本不一致')));
});

test('sensitive read output is redacted and a task board opens a read-only deep view', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('tool_execution_start', { toolCallId: 'secret-call', toolName: 'read', args: { path: '.env' } });
  await f.emit('tool_execution_end', { toolCallId: 'secret-call', toolName: 'read', args: { path: '.env' },
    result: { content: [{ type: 'text', text: 'synthetic-confidential-content' }] }, isError: false });
  const event = (await f.events('one')).find(entry => entry.node === 'secret-call');
  const data = f.flow('evidence', 'one', event.evidence, '--json');
  assert.ok(!data.includes('synthetic-confidential-content'));
  assert.ok(data.includes('REDACTED'));
  assert.ok(f.commands.has('workflow'));
  f.selections.push('流程', 'secret-call');
  await f.commands.get('workflow').handler('one T01', f.ctx);
  assert.ok(f.screens.length > 0);
  assert.ok(f.screens.some(text => text.includes('REDACTED')));
  assert.ok(!f.notices.some(notice => notice.type === 'editor'));
});

test('registered Skill reads preserve final tool input, actual output and truncation metadata', options, async t => {
  const f = await fixture(t);
  const path = join(f.cwd, 'SKILL.md');
  await writeFile(path, 'new disk version');
  f.registered.push({ name: 'skill:sample', source: 'skill', sourceInfo: { path, source: 'cli', scope: 'temporary', origin: 'top-level' } });
  await f.scope('one');
  await f.emit('tool_execution_start', { toolCallId: 'skill-read', toolName: 'read', args: { path: 'old-path', offset: 1 } });
  await f.emit('tool_result', { toolCallId: 'skill-read', toolName: 'read', input: { path, offset: 7, limit: 3 } });
  await f.emit('tool_execution_end', { toolCallId: 'skill-read', toolName: 'read',
    result: { content: [{ type: 'text', text: 'actually observed older Skill lines' }], details: { truncation: { truncated: true } } }, isError: false });
  const board = JSON.parse(f.flow('board', 'one', 'T01', '--json'));
  const skill = board.skills.find(item => item.name === 'sample');
  assert.equal(skill.source, 'pi-read');
  const detail = JSON.parse(f.flow('evidence', 'one', skill.evidence, '--json'));
  assert.equal(detail.input.offset, 7);
  assert.equal(detail.inputObservation, 'tool_result最终输入');
  assert.equal(detail.output.details.truncation.truncated, true);
  assert.equal(detail.output.content[0].text, 'actually observed older Skill lines');
});

test('binding a node mid-run preserves the one observed agent identity across scopes', options, async t => {
  const f = await fixture(t);
  await f.emit('agent_start');
  await f.scope('one');
  await f.scope('two');
  const first = (await f.events('one')).find(e => e.kind === 'agent');
  const second = (await f.events('two')).find(e => e.kind === 'agent');
  assert.ok(first && second);
  assert.equal(first.node, second.node);
  assert.equal(first.source, 'pi-event');
});

test('explicit agent declarations are not labeled as observed capabilities', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.tools.get('ai_workflow_record').execute('record',
    { kind: 'delegation', name: 'proposed-review', summary: '建议委派，尚未调用', detail: { status: 'planned' } },
    undefined, undefined, f.ctx);
  const entry = (await f.events('one')).find(e => e.name === 'proposed-review');
  assert.equal(entry.source, 'declared');
});

test('recording failure keeps a visible, recoverable gap on the original task', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('tool_execution_start', { toolCallId: 'lost-call', toolName: 'read', args: { path: 'source.txt' } });
  await f.scope('two');
  f.ctx.cwd = join(f.cwd, 'missing-directory');
  await f.emit('tool_execution_end', { toolCallId: 'lost-call', toolName: 'read',
    result: { content: [{ type: 'text', text: 'retained in the host tool transcript' }] }, isError: false });
  const gap = f.entries.find(entry => entry.customType === 'ai-workflow-audit-gap');
  assert.equal(gap.data.scope.requirement, 'one');
  assert.equal(gap.data.node, 'lost-call');
  assert.ok(f.notices.some(notice => notice.text.includes('审计不完整')));
  await f.emit('session_start', { reason: 'resume' });
  assert.ok(f.notices.some(notice => notice.text.includes('保留观察缺口')));
});

test('reload cancels queued observations without using stale session APIs', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('tool_execution_start', { toolCallId: 'interrupted', toolName: 'bash', args: { command: 'true' } });
  const pending = f.emit('tool_execution_end', { toolCallId: 'interrupted', toolName: 'bash', result: { content: [] }, isError: false });
  await f.emit('session_shutdown', { reason: 'reload' });
  await pending;
  assert.ok(f.entries.some(entry => entry.customType === 'ai-workflow-audit-gap' && entry.data.node === 'interrupted'));
  await f.emit('session_start', { reason: 'reload' });
});

test('a new workflow Skill clears the previous scope durably across resume', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('input', { text: '/skill:ai-workflow a new requirement' });
  await f.emit('before_agent_start', { messageType: 'user',
    prompt: '<skill name="ai-workflow" location="/skills/ai-workflow/SKILL.md">\nnew requirement', systemPromptOptions: { contextFiles: [] } });
  await f.emit('session_start', { reason: 'resume' });
  await f.emit('tool_execution_start', { toolCallId: 'new-unscoped', toolName: 'read', args: { path: 'new.txt' } });
  await f.emit('tool_execution_end', { toolCallId: 'new-unscoped', toolName: 'read', result: { content: [] }, isError: false });
  assert.ok(!(await f.events('one')).some(event => event.node === 'new-unscoped'));
});

test('scope restores only from the active branch', options, async t => {
  const f = await fixture(t);
  await f.scope('one');
  await f.emit('session_start', { reason: 'resume' });
  await f.emit('tool_execution_start', { toolCallId: 'restored', toolName: 'read', args: { path: 'file.txt' } });
  await f.emit('tool_execution_end', { toolCallId: 'restored', toolName: 'read', args: { path: 'file.txt' }, result: { content: [] }, isError: true });
  assert.ok((await f.events('one')).some(event => event.node === 'restored'));
  f.entries.length = 0;
  await f.emit('session_tree');
  await f.emit('tool_execution_start', { toolCallId: 'unscoped', toolName: 'read', args: { path: 'file.txt' } });
  await f.emit('tool_execution_end', { toolCallId: 'unscoped', toolName: 'read', args: { path: 'file.txt' }, result: { content: [] }, isError: false });
  assert.ok(!(await f.events('one')).some(event => event.node === 'unscoped'));
});
