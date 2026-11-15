const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
const start = source.indexOf('  function paperAuthor(');
const end = source.indexOf('\n  function paperVersion(', start);
assert.ok(start >= 0 && end > start);
const paperAuthor = vm.runInNewContext(source.slice(start, end) + '\npaperAuthor');

test('authors are limited to five with etc only when additional authors exist', () => {
  assert.equal(paperAuthor({ authors: ['A', 'B', 'C', 'D', 'E', 'F'], author: 'wrong fallback' }), 'A, B, C, D, E, etc');
  assert.equal(paperAuthor({ authors: ['A', 'B', 'C', 'D', 'E'] }), 'A, B, C, D, E');
  assert.equal(paperAuthor({ authors: ['A', 'B'] }), 'A, B');
});

test('legacy author strings and missing author metadata still display correctly', () => {
  assert.equal(paperAuthor({ author: 'A, B, C, D, E, F' }), 'A, B, C, D, E, etc');
  assert.equal(paperAuthor({ author: '甲；乙；丙' }), '甲, 乙, 丙');
  assert.equal(paperAuthor({ author: '  One Author  ' }), 'One Author');
  assert.equal(paperAuthor({ authors: [], author: '' }), '未填写作者');
});
