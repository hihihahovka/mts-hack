<script>
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { updateMemoryById } from '$lib/apis/memories';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const dispatch = createEventDispatcher();

	export let show;
	export let memory = {};

	const i18n = getContext('i18n');

	let loading = false;
	let factContent = '';
	let tagPrefix = '';
	let baseCategory = '';

	const CATEGORY_COLORS = {
		IDENTITY: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-300' },
		USER: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-300' },
		FEEDBACK: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300' },
		PROJECT: { bg: 'bg-purple-100 dark:bg-purple-900/40', text: 'text-purple-700 dark:text-purple-300' },
		LOCAL: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-500 dark:text-gray-400' },
	};

	const CATEGORY_LABELS = {
		IDENTITY: '🪪 Identity',
		USER: '⚙️ Preferences',
		FEEDBACK: '📏 Behavioral Rules',
		PROJECT: '📁 Project',
		LOCAL: '💬 Local',
	};

	function parseMemory(content) {
		if (!content) return { tag: '', fact: '', base: '' };
		const match = content.match(/^(\[([A-Z]+)(?::[^\]]+)?\])\s*/);
		if (!match) return { tag: '', fact: content, base: '' };
		return { tag: match[1], fact: content.slice(match[0].length), base: match[2] };
	}

	$: if (show) {
		setContent();
	}

	const setContent = () => {
		const parsed = parseMemory(memory?.content || '');
		tagPrefix = parsed.tag;
		baseCategory = parsed.base;
		factContent = parsed.fact;
	};

	function getCatColors(cat) {
		return CATEGORY_COLORS[cat] || CATEGORY_COLORS['LOCAL'];
	}

	const submitHandler = async () => {
		if (!factContent.trim()) {
			toast.error($i18n.t('Memory cannot be empty'));
			return;
		}

		loading = true;

		// Reconstruct full content: tag + edited fact
		const fullContent = tagPrefix ? `${tagPrefix} ${factContent.trim()}` : factContent.trim();

		const res = await updateMemoryById(localStorage.token, memory.id, fullContent).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Memory updated successfully'));
			dispatch('save');
			show = false;
		}

		loading = false;
	};
</script>

<Modal bind:show size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Edit Memory')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<form
				class="flex flex-col w-full gap-3"
				on:submit|preventDefault={() => {
					submitHandler();
				}}
			>
				<!-- Category badge (read-only) -->
				{#if baseCategory}
					{@const colors = getCatColors(baseCategory)}
					<div class="flex items-center gap-2">
						<span class="inline-flex items-center px-2 py-1 rounded-lg text-xs font-semibold {colors.bg} {colors.text}">
							{CATEGORY_LABELS[baseCategory] || baseCategory}
						</span>
						{#if tagPrefix.includes(':folder:')}
							<span class="text-xs text-gray-400 dark:text-gray-500">
								Folder-scoped
							</span>
						{/if}
						{#if tagPrefix.includes(':chat:')}
							<span class="text-xs text-gray-400 dark:text-gray-500">
								Chat-scoped
							</span>
						{/if}
					</div>
				{/if}

				<!-- Fact content editor -->
				<div>
					<textarea
						bind:value={factContent}
						class="bg-transparent w-full text-sm rounded-xl p-3 outline outline-1 outline-gray-100 dark:outline-gray-800 focus:outline-gray-300 dark:focus:outline-gray-600 transition"
						rows="5"
						style="resize: vertical;"
						placeholder={$i18n.t('Enter a detail about yourself for your LLMs to recall')}
					/>

					{#if tagPrefix}
						<div class="text-[0.65rem] text-gray-400 dark:text-gray-500 mt-1 font-mono">
							{$i18n.t('Tag')}: <code class="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">{tagPrefix}</code>
						</div>
					{/if}
				</div>

				<div class="flex justify-end text-sm font-medium">
					<button
						class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex items-center gap-2 whitespace-nowrap {loading
							? ' cursor-not-allowed'
							: ''}"
						type="submit"
						disabled={loading}
					>
						{$i18n.t('Update')}

						{#if loading}
							<span class="shrink-0">
								<Spinner />
							</span>
						{/if}
					</button>
				</div>
			</form>
		</div>
	</div>
</Modal>
