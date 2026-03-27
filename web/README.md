# OSPR Dashboard

A pipeline dashboard for the oz-for-oss repository that visualizes the issue-to-implementation workflow and provides a first-class spec review experience.

## Features

- **Pipeline Board** — Kanban-style view of issues and PRs across four workflow stages: Ready to Spec → Spec in Review → Ready to Implement → Code in Review
- **Issue Detail** — Full issue view with inline spec rendering, pipeline stage indicator, and links to associated PRs
- **Spec Reviewer** — Tabbed product/tech spec viewer with rich markdown rendering, syntax highlighting, and auto-generated table of contents
- **PR Detail** — PR view that shows spec context inline (for spec PRs) or in a collapsible panel (for code PRs), with changed file summaries

## Setup

```sh
cd web
npm install
```

Copy `.env.example` to `.env.local` and configure:

```sh
cp .env.example .env.local
```

Set `GITHUB_TOKEN` if you need higher API rate limits (optional for public repos).

## Development

```sh
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Build

```sh
npm run build
npm start
```

## Tech Stack

- [Next.js](https://nextjs.org/) (App Router, Server Components)
- [ShadCN/ui](https://ui.shadcn.com/) + [Tailwind CSS](https://tailwindcss.com/)
- [react-markdown](https://github.com/remarkjs/react-markdown) with remark-gfm and rehype-highlight
- [Lucide React](https://lucide.dev/) icons
- GitHub REST API (server-side only)
