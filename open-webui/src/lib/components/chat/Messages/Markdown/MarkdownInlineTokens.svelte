<script lang="ts">
	import DOMPurify from 'dompurify';
	import { toast } from 'svelte-sonner';

	import type { Token } from 'marked';
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';

	const i18n = getContext('i18n');

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { copyToClipboard, unescapeHtml } from '$lib/utils';

	// ── Citation Pill helpers ──────────────────────────────────────────────────
	// Матчит ссылки вида [(N)](url) — текст токена = "(3)" или "(12)"
	const CITATION_RE = /^\((\d+)\)$/;

	function isCitationLink(token: Token & { href?: string; text?: string; tokens?: Token[] }): boolean {
		if (!token.href || !token.href.startsWith('http')) return false;
		const rawText = (token.tokens?.map((t: any) => t.raw ?? t.text ?? '').join('') ?? token.text ?? '').trim();
		return CITATION_RE.test(rawText);
	}

	function getCitationNum(token: Token & { text?: string; tokens?: Token[] }): string {
		const rawText = (token.tokens?.map((t: any) => t.raw ?? t.text ?? '').join('') ?? token.text ?? '').trim();
		return CITATION_RE.exec(rawText)?.[1] ?? '?';
	}

	function getCitationDomain(href: string): string {
		try {
			const u = new URL(href);
			return u.hostname.replace(/^www\./, '');
		} catch {
			return '';
		}
	}
	// ──────────────────────────────────────────────────────────────────────────

	import Image from '$lib/components/common/Image.svelte';
	import KatexRenderer from './KatexRenderer.svelte';
	import Source from './Source.svelte';
	import HtmlToken from './HTMLToken.svelte';
	import TextToken from './MarkdownInlineTokens/TextToken.svelte';
	import CodespanToken from './MarkdownInlineTokens/CodespanToken.svelte';
	import MentionToken from './MarkdownInlineTokens/MentionToken.svelte';
	import NoteLinkToken from './MarkdownInlineTokens/NoteLinkToken.svelte';
	import SourceToken from './SourceToken.svelte';

	export let id: string;
	export let done = true;
	export let tokens: Token[];
	export let sourceIds = [];
	export let onSourceClick: Function = () => {};

	/**
	 * Check if a URL is a same-origin note link and return the note ID if so.
	 */
	const getNoteIdFromHref = (href: string): string | null => {
		try {
			const url = new URL(href, window.location.origin);
			if (url.origin === window.location.origin) {
				const match = url.pathname.match(/^\/notes\/([^/]+)$/);
				if (match) {
					return match[1];
				}
			}
		} catch {
			// Invalid URL
		}
		return null;
	};

	/**
	 * Handle link clicks - intercept same-origin app URLs for in-app navigation
	 */
	const handleLinkClick = (e: MouseEvent, href: string) => {
		try {
			const url = new URL(href, window.location.origin);
			// Check if same origin and an in-app route
			if (
				url.origin === window.location.origin &&
				(url.pathname.startsWith('/notes/') ||
					url.pathname.startsWith('/c/') ||
					url.pathname.startsWith('/channels/'))
			) {
				e.preventDefault();
				goto(url.pathname + url.search + url.hash);
			}
		} catch {
			// Invalid URL, let browser handle it
		}
	};
</script>

{#each tokens as token, tokenIdx (tokenIdx)}
	{#if token.type === 'escape'}
		{unescapeHtml(token.text)}
	{:else if token.type === 'html'}
		<HtmlToken {id} {token} {onSourceClick} />
	{:else if token.type === 'link'}
		{@const noteId = getNoteIdFromHref(token.href)}
		{#if noteId}
			<NoteLinkToken {noteId} href={token.href} />
		{:else if isCitationLink(token)}
			{@const num = getCitationNum(token)}
			{@const domain = getCitationDomain(token.href)}
			<a
				class="mts-cite-pill"
				href={token.href}
				target="_blank"
				rel="noopener noreferrer"
				title={token.href}
				on:click={(e) => handleLinkClick(e, token.href)}
			>
				<span class="mts-cite-pill__num">{num}</span>
				{#if domain}
					<span class="mts-cite-pill__label">{domain}</span>
				{/if}
			</a>
		{:else if token.tokens}
			<a
				href={token.href}
				target="_blank"
				rel="nofollow"
				title={token.title}
				on:click={(e) => handleLinkClick(e, token.href)}
			>
				<svelte:self id={`${id}-a`} tokens={token.tokens} {onSourceClick} {done} />
			</a>
		{:else}
			<a
				href={token.href}
				target="_blank"
				rel="nofollow"
				title={token.title}
				on:click={(e) => handleLinkClick(e, token.href)}>{token.text}</a
			>
		{/if}
	{:else if token.type === 'image'}
		<Image src={token.href} alt={token.text} />
	{:else if token.type === 'strong'}
		<strong><svelte:self id={`${id}-strong`} tokens={token.tokens} {onSourceClick} /></strong>
	{:else if token.type === 'em'}
		<em><svelte:self id={`${id}-em`} tokens={token.tokens} {onSourceClick} /></em>
	{:else if token.type === 'codespan'}
		<CodespanToken {token} {done} />
	{:else if token.type === 'br'}
		<br />
	{:else if token.type === 'del'}
		<del><svelte:self id={`${id}-del`} tokens={token.tokens} {onSourceClick} /></del>
	{:else if token.type === 'inlineKatex'}
		{#if token.text}
			<KatexRenderer content={token.text} displayMode={false} />
		{/if}
	{:else if token.type === 'iframe'}
		<iframe
			src="{WEBUI_BASE_URL}/api/v1/files/{token.fileId}/content"
			title={token.fileId}
			width="100%"
			frameborder="0"
			on:load={(e) => {
				try {
					e.currentTarget.style.height =
						e.currentTarget.contentWindow.document.body.scrollHeight + 20 + 'px';
				} catch {}
			}}
		></iframe>
	{:else if token.type === 'mention'}
		<MentionToken {token} />
	{:else if token.type === 'footnote'}
		{@html DOMPurify.sanitize(
			`<sup class="footnote-ref footnote-ref-text">${token.escapedText}</sup>`
		) || ''}
	{:else if token.type === 'citation'}
		{#if (sourceIds ?? []).length > 0}
			<SourceToken {id} {token} {sourceIds} onClick={onSourceClick} />
		{:else}
			<TextToken {token} {done} />
		{/if}
	{:else if token.type === 'text'}
		<TextToken {token} {done} />
	{/if}
{/each}

<style>
	/* ── Citation Pill ── */
	a.mts-cite-pill {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin: 0 2px;
		padding: 1px 8px 1px 4px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 500;
		line-height: 1.6;
		white-space: nowrap;
		max-width: 160px;
		overflow: hidden;
		text-decoration: none;
		cursor: pointer;
		vertical-align: middle;
		position: relative;
		top: -1px;
		transition:
			background 0.15s ease,
			box-shadow 0.15s ease,
			transform 0.1s ease;
		/* light mode */
		background: #FF0032;
		color: #FFFFFF;
		border: 1px solid #FF0032;
	}

	:global(.dark) a.mts-cite-pill {
		background: #FF0032;
		color: #FFFFFF;
		border: 1px solid #FF0032;
	}

	a.mts-cite-pill:hover {
		background: #E6002D;
		box-shadow: 0 1px 6px rgba(255, 0, 50, 0.40);
		transform: translateY(-1px);
	}

	:global(.dark) a.mts-cite-pill:hover {
		background: #E6002D;
		box-shadow: 0 1px 6px rgba(255, 0, 50, 0.40);
	}

	a.mts-cite-pill:active {
		transform: translateY(0);
	}

	a.mts-cite-pill .mts-cite-pill__num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		border-radius: 50%;
		font-size: 9.5px;
		font-weight: 700;
		flex-shrink: 0;
		background: rgba(255, 255, 255, 0.25);
		color: inherit;
	}

	:global(.dark) a.mts-cite-pill .mts-cite-pill__num {
		background: rgba(255, 255, 255, 0.25);
	}

	a.mts-cite-pill .mts-cite-pill__label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 120px;
	}
</style>
