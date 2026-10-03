import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { test } from 'node:test';

test('initializing the destructive action requires fresh confirmation even if the browser restored a value', async () => {
  const source = await readFile(new URL('../static/app.js', import.meta.url), 'utf8');
  const start = source.indexOf('function setupClearKnowledgeGuard()');
  const script = source.slice(start, source.indexOf('\nsetupEmbeddedStateBridge();', start));
  let input;
  const confirmation = { value: '清空知识库', dataset: { confirmPhrase: '清空知识库' }, addEventListener: (_type, fn) => { input = fn; } };
  const button = { disabled: false, addEventListener() {} };
  const document = { getElementById: id => id === 'clear-knowledge' ? button : confirmation };
  vm.runInNewContext(script + '\nsetupClearKnowledgeGuard();', { document });
  assert.equal(confirmation.value, '');
  assert.equal(button.disabled, true);
  confirmation.value = '清空知识库';
  input();
  assert.equal(button.disabled, false);
});
