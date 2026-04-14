<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Search from '$lib/components/icons/Search.svelte';

	import EditMemoryModal from './EditMemoryModal.svelte';
	import { deleteMemoryById, getMemories } from '$lib/apis/memories';

	dayjs.extend(localizedFormat);
	const i18n = getContext('i18n');

	export let show = false;
	export let chatId: string;

	let memories = [];
	let loading = true;
	let query = '';

	let showEditMemoryModal = false;
	let selectedMemory = null;

	let showClearConfirmDialog = false;
	let showDeleteConfirm = false;

	function parseTag(content: string) {
		const match = content.match(/^\[([A-Z]+)(?::([^\]]+))?\]\s*/);
		if (!match) return { baseCategory: '', fullTag: '', chatId: null, fact: content };

		const baseCategory = match[1];
		const suffix = match[2] || '';
		let currentChatId: string | null = null;

		if (suffix.startsWith('chat:')) {
			currentChatId = suffix.replace('chat:', '');
		}

		let cleanFact = content.slice(match[0].length).replace(/\[[A-Z]+(?::[^\]]+)?\]/g, '').trim();

		return { baseCategory, chatId: currentChatId, fact: cleanFact };
	}

	// Filter strictly for memories matching this chat scope
	$: localMemories = (memories || []).filter((m) => {
		const parsed = parseTag(m.content);
		return parsed.baseCategory === 'LOCAL' && parsed.chatId === chatId;
	});

	$: filteredMemories = query
		? localMemories.filter((m) => m.content?.toLowerCase().includes(query.toLowerCase()))
		: localMemories;

	$: sortedMemories = [...filteredMemories].sort((a, b) => b.updated_at - a.updated_at);

	let onClearConfirmed = async () => {
		if (localMemories.length === 0) return;

		loading = true;
		showClearConfirmDialog = false;
		let successCount = 0;

		for (const m of localMemories) {
			const res = await deleteMemoryById(localStorage.token, m.id).catch(() => null);
			if (res) successCount++;
		}

		if (successCount > 0) {
			toast.success($i18n.t(`Cleared ${successCount} local memories`));
			const clearedSet = new Set(localMemories.map((m) => m.id));
			memories = (memories || []).filter((m) => !clearedSet.has(m.id));
		}
		loading = false;
	};

	$: if (show) {
		(async () => {
			loading = true;
			memories = await getMemories(localStorage.token);
			loading = false;
		})();
	}
</script>

<Modal size="lg" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class="text-lg font-medium">{$i18n.t('Local Chat Memory')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-4" />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-5 py-4 md:space-x-4 dark:text-gray-200">
			<div class="flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<!-- Search -->
				<div class="flex flex-1 items-center w-full mb-3 bg-gray-50/50 dark:bg-gray-850/50 px-3 rounded-full border border-gray-100 dark:border-gray-800">
					<div class="self-center mr-2 text-gray-400">
						<Search className="size-3.5" />
					</div>
					<input
						class="w-full text-sm py-1.5 outline-none bg-transparent dark:text-gray-200"
						bind:value={query}
						placeholder={$i18n.t('Search local memories...')}
						maxlength="500"
					/>
					{#if query}
						<button
							class="p-1 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition"
							on:click={() => (query = '')}
						>
							<XMark className="size-3" strokeWidth="2" />
						</button>
					{/if}
				</div>
			</div>
		</div>

		<div class="px-5 pb-5">
			<div class="flex flex-col w-full">
				{#if !loading}
					{#if sortedMemories.length === 0}
						<div class="text-xs text-gray-400 dark:text-gray-500 text-center px-5 min-h-20 w-full flex justify-center items-center">
							{#if localMemories.length === 0}
								{$i18n.t('No local memories found for this chat yet.')}
							{:else}
								{$i18n.t('No results found')}
							{/if}
						</div>
					{:else}
						<!-- Flat list of local memories -->
						<div class="text-left text-sm w-full max-h-[28rem] overflow-y-auto space-y-1">
							{#each sortedMemories as memory (memory.id)}
								{@const parsed = parseTag(memory.content)}
								<div
									class="w-full flex justify-between items-center rounded-xl text-sm py-2 px-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition cursor-pointer group border border-transparent hover:border-gray-100 dark:hover:border-gray-800"
									on:click={() => {
										selectedMemory = memory;
										showEditMemoryModal = true;
									}}
								>
									<div class="flex-1 min-w-0 pr-2">
										<div class="flex items-center gap-2">
											<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[0.6rem] font-semibold uppercase bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 shrink-0">
												LOCAL
											</span>
											<span class="text-ellipsis line-clamp-1">{parsed.fact}</span>
										</div>
										<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 ml-[42px]">
											{dayjs(memory.updated_at * 1000).format('MMM D, YYYY · h:mm A')}
										</div>
									</div>

									<div class="flex items-center shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
										<Tooltip content={$i18n.t('Edit')}>
											<button
												class="p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
												on:click|stopPropagation={() => {
													selectedMemory = memory;
													showEditMemoryModal = true;
												}}
											>
												<Pencil className="size-3.5" />
											</button>
										</Tooltip>
										<Tooltip content={$i18n.t('Delete')}>
											<button
												class="p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
												on:click|stopPropagation={() => {
													selectedMemory = memory;
													showDeleteConfirm = true;
												}}
											>
												<GarbageBin className="size-3.5" strokeWidth="1.5" />
											</button>
										</Tooltip>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="w-full flex justify-center items-center min-h-20">
						<Spinner className="size-4" />
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="flex justify-between items-center text-sm mt-3 pt-2 border-t border-gray-100 dark:border-gray-800">
				<button
					class="px-2 py-1 text-xs text-gray-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 hover:underline transition"
					disabled={localMemories.length === 0}
					on:click={() => {
						showClearConfirmDialog = true;
					}}
				>
					{$i18n.t('Clear all local memory')}
				</button>
			</div>
		</div>
	</div>
</Modal>

<ConfirmDialog
	title={$i18n.t('Clear Local Memory')}
	message={$i18n.t('Are you sure you want to clear all local memories for this chat? This action cannot be undone.')}
	show={showClearConfirmDialog}
	on:confirm={onClearConfirmed}
	on:cancel={() => {
		showClearConfirmDialog = false;
	}}
/>

<ConfirmDialog
	title={$i18n.t('Delete Memory?')}
	show={showDeleteConfirm}
	on:confirm={async () => {
		const res = await deleteMemoryById(localStorage.token, selectedMemory.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Memory deleted successfully'));
			memories = memories.filter((m) => m.id !== selectedMemory.id);
		}
		showDeleteConfirm = false;
	}}
	on:cancel={() => {
		showDeleteConfirm = false;
	}}
>
	<div class="text-sm text-gray-500">
		<div
			class=" mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded-xl border border-gray-100 dark:border-gray-800 text-black dark:text-white whitespace-pre-wrap break-words max-h-32 overflow-y-auto"
		>
			{selectedMemory?.content}
		</div>
	</div>
</ConfirmDialog>

<EditMemoryModal
	bind:show={showEditMemoryModal}
	memory={selectedMemory}
	on:save={() => {
		(async () => {
			memories = await getMemories(localStorage.token);
		})();
	}}
/>
