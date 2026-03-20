import { appendFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';

function getInput(name) {
  return process.env[`INPUT_${name.toUpperCase()}`] ?? '';
}

function setOutput(name, value) {
  if (!process.env.GITHUB_OUTPUT) {
    return;
  }

  const delimiter = `oz_${crypto.randomUUID()}`;
  appendFileSync(process.env.GITHUB_OUTPUT, `${name}<<${delimiter}\n${value}\n${delimiter}\n`);
}

async function updateIssueCommentWithSessionUrl(sessionUrl) {
  const githubToken = getInput('github_token');
  const commentId = getInput('comment_id');
  const statusMessage = getInput('status_message');
  const commentMetadata = getInput('comment_metadata');
  const repository = process.env.GITHUB_REPOSITORY;

  if (!githubToken || !commentId || !statusMessage || !repository) {
    return;
  }

  const bodyLines = [
    statusMessage,
    '',
    `Sharing session at: ${sessionUrl}`,
  ];

  if (commentMetadata) {
    bodyLines.push('', commentMetadata);
  }

  const response = await fetch(`https://api.github.com/repos/${repository}/issues/comments/${commentId}`, {
    method: 'PATCH',
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${githubToken}`,
      'Content-Type': 'application/json',
      'User-Agent': 'oz-agent-local-action',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify({
      body: bodyLines.join('\n'),
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    process.stderr.write(`::warning::Failed to update issue comment with session URL: ${errorText}\n`);
  }
}

async function main() {
  const prompt = getInput('prompt');
  const savedPrompt = getInput('saved_prompt');
  const skill = getInput('skill');
  const model = getInput('model');
  const name = getInput('name');
  const mcp = getInput('mcp');
  const cwd = getInput('cwd');
  const profile = getInput('profile');
  const outputFormat = getInput('output_format');
  const apiKey = getInput('warp_api_key');
  const share = getInput('share');
  const channel = getInput('oz_channel') || 'stable';

  if (!prompt && !savedPrompt && !skill) {
    throw new Error('Either `prompt`, `saved_prompt`, or `skill` must be provided.');
  }

  if (!apiKey) {
    throw new Error('`warp_api_key` must be provided.');
  }

  let command;
  switch (channel) {
    case 'stable':
      command = 'oz';
      break;
    case 'preview':
      command = 'oz-preview';
      break;
    default:
      throw new Error(`Unsupported channel ${channel}`);
  }

  const args = ['agent', 'run'];

  if (prompt) {
    args.push('--prompt', prompt);
  }

  if (savedPrompt) {
    args.push('--saved-prompt', savedPrompt);
  }

  if (skill) {
    args.push('--skill', skill);
  }

  if (model) {
    args.push('--model', model);
  }

  if (name) {
    args.push('--name', name);
  }

  if (mcp) {
    args.push('--mcp', mcp);
  }

  if (cwd) {
    args.push('--cwd', cwd);
  }

  if (profile) {
    args.push('--profile', profile);
  } else {
    args.push('--sandboxed');
  }

  if (outputFormat) {
    args.push('--output-format', outputFormat);
  }

  const shareRecipients = share
    .split(/\r?\n/)
    .map((recipient) => recipient.trim())
    .filter(Boolean);

  for (const recipient of shareRecipients) {
    args.push('--share', recipient);
  }

  const child = spawn(command, args, {
    cwd: cwd || process.cwd(),
    env: {
      ...process.env,
      WARP_API_KEY: apiKey,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let scanBuffer = '';
  let sessionUrl = '';
  let sessionUrlUpdatePromise = Promise.resolve();

  const scanForSessionUrl = (text) => {
    scanBuffer = `${scanBuffer}${text}`.slice(-16384);

    if (sessionUrl) {
      return;
    }

    const match = scanBuffer.match(/Sharing session at:\s*(https:\/\/app\.warp\.dev\/session\/[^\s]+)/);
    if (!match) {
      return;
    }

    sessionUrl = match[1];
    setOutput('session_url', sessionUrl);
    sessionUrlUpdatePromise = updateIssueCommentWithSessionUrl(sessionUrl);
  };

  child.stdout.on('data', (chunk) => {
    const text = chunk.toString();
    process.stdout.write(text);
    scanForSessionUrl(text);
  });

  child.stderr.on('data', (chunk) => {
    const text = chunk.toString();
    process.stderr.write(text);
    scanForSessionUrl(text);
  });

  const exitCode = await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', (code, signal) => {
      if (signal) {
        reject(new Error(`Oz terminated with signal ${signal}`));
        return;
      }

      resolve(code ?? 1);
    });
  });

  await sessionUrlUpdatePromise;

  if (exitCode !== 0) {
    process.exit(exitCode);
  }
}

main().catch((error) => {
  process.stderr.write(`::error::${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
