import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import ts from 'typescript';
import { parse } from '@vue/compiler-sfc';

const require = createRequire(import.meta.url);
const { baseParse } = createRequire(require.resolve('vue'))('@vue/compiler-dom');
const root = path.resolve(import.meta.dirname, '../src');
const messages = JSON.parse(fs.readFileSync(path.join(root, 'i18n/zh-CN.json'), 'utf8'));
const errors = [];
const used = new Set();
const normalize = (value) => value.replace(/\s+/g, ' ').trim();
const tokens = (value) => [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

function inspect(source, file) {
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(ast) === 'tr') {
      const message = node.arguments[0];
      if (message && ts.isStringLiteralLike(message)) {
        const key = normalize(message.text);
        used.add(key);
        if (!messages[key]) errors.push(`${file}: missing Chinese translation for ${key}`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
}

function inspectTemplate(node, file) {
  if (node.type === 5) inspect(`const text = (${node.content.content});`, file);
  for (const prop of node.props ?? []) {
    if (prop.type === 7 && prop.exp) inspect(`const value = (${prop.exp.content});`, file);
  }
  for (const child of node.children ?? []) inspectTemplate(child, file);
}

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (file.endsWith('.vue')) {
      const { descriptor } = parse(fs.readFileSync(file, 'utf8'));
      if (descriptor.scriptSetup) inspect(descriptor.scriptSetup.content, file);
      if (descriptor.script) inspect(descriptor.script.content, file);
      if (descriptor.template) inspectTemplate(baseParse(descriptor.template.content), file);
    } else if (file.endsWith('.ts') && !file.endsWith('.d.ts')) {
      inspect(fs.readFileSync(file, 'utf8'), file);
    }
  }
}

walk(root);
for (const [key, value] of Object.entries(messages)) {
  if (typeof value !== 'string' || value.length === 0) errors.push(`Empty translation: ${key}`);
  else if (JSON.stringify(tokens(key)) !== JSON.stringify(tokens(value))) {
    errors.push(`Interpolation parameters differ: ${key}`);
  }
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log(
    `Checked ${used.size} UI messages and ${Object.keys(messages).length} Chinese translations.`,
  );
}
