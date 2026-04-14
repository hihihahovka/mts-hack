<script>
	import { createEventDispatcher, getContext } from 'svelte';

	import Modal from '$lib/components/common/Modal.svelte';
	import { addNewMemory } from '$lib/apis/memories';
	import { toast } from 'svelte-sonner';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const dispatch = createEventDispatcher();

	export let show;
	export let category = ''; // preset category (e.g. 'PROJECT')
	export let folderId = null; // if set, auto-scope to folder

	const i18n = getContext('i18n');

	let loading = false;
	let content = '';
	let selectedCategory = 'USER';

	const CATEGORIES = [
		{ value: 'IDENTITY', label: '🪪 Identity', desc: 'Name, profession, location, family' },
		{ value: 'USER', label: '⚙️ Preferences', desc: 'Tastes, preferences, minor details' },
		{ value: 'FEEDBACK', label: '📏 Behavioral Rules', desc: 'How AI should behave' },
		{ value: 'PROJECT', label: '📁 Project', desc: 'Tech stack, architecture, decisions' },
	];

	const CATEGORY_COLORS = {
		IDENTITY: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800',
		USER: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
		FEEDBACK: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
		PROJECT: 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800',
	};

	$: if (show) {
		if (category) {
			selectedCategory = category;
		} else {
			selectedCategory = 'USER';
		}
	}

	$: isFolder = !!folderId;

	const submitHandler = async () => {
		if (!content.trim()) {
			toast.error($i18n.t('Please enter a memory'));
			return;
		}

		loading = true;

		// Build tagged content
		let taggedContent;
		if (isFolder) {
			taggedContent = `[PROJECT:folder:${folderId}] ${content.trim()}`;
		} else {
			taggedContent = `[${selectedCategory}] ${content.trim()}`;
		}

		const res = await addNewMemory(localStorage.token, taggedContent).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Memory added successfully'));
			content = '';
			show = false;
			dispatch('save');
		}

		loading = false;
	};
</script>

<Modal bind:show size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Add Memory')}
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
				<!-- Category selector (hidden when adding to a folder) -->
				{#if !isFolder}
					<div>
						<label class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 block">
							{$i18n.t('Category')}
						</label>
						<div class="grid grid-cols-2 gap-1.5">
							{#each CATEGORIES as cat}
								<button
									type="button"
									class="px-2.5 py-2 rounded-xl border text-left transition-all text-xs
										{selectedCategory === cat.value
											? `${CATEGORY_COLORS[cat.value]} border-current font-medium ring-1 ring-current/20`
											: 'border-gray-100 dark:border-gray-800 hover:border-gray-200 dark:hover:border-gray-700 text-gray-600 dark:text-gray-400'}"
									on:click={() => (selectedCategory = cat.value)}
								>
									<div class="font-medium">{cat.label}</div>
									<div class="text-[0.6rem] opacity-60 mt-0.5">{cat.desc}</div>
								</button>
							{/each}
						</div>
					</div>
				{:else}
					<!-- Folder indicator -->
					<div class="flex items-center gap-2 px-3 py-2 rounded-xl bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800">
						<span class="text-xs font-semibold text-purple-600 dark:text-purple-400">📁 PROJECT</span>
						<span class="text-xs text-purple-500 dark:text-purple-400">→ Folder-scoped memory</span>
					</div>
				{/if}

				<!-- Content -->
				<div>
					<textarea
						bind:value={content}
						class="bg-transparent w-full text-sm rounded-xl p-3 outline outline-1 outline-gray-100 dark:outline-gray-800 focus:outline-gray-300 dark:focus:outline-gray-600 transition"
						rows="4"
						style="resize: vertical;"
						placeholder={$i18n.t('Enter a fact to remember (e.g., "User prefers dark mode")')}
					/>

					<div class="text-xs text-gray-400 mt-1">
						ⓘ {$i18n.t('Refer to yourself as "User" (e.g., "User is learning Spanish")')}
					</div>
				</div>

				<div class="flex justify-end text-sm font-medium">
					<button
						class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex items-center gap-2 whitespace-nowrap {loading
							? ' cursor-not-allowed'
							: ''}"
						type="submit"
						disabled={loading}
					>
						{$i18n.t('Add')}

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
