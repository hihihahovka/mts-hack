<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import Modal from '$lib/components/common/Modal.svelte';
	import AddMemoryModal from './AddMemoryModal.svelte';
	import { deleteMemoriesByUserId, deleteMemoryById, getMemories } from '$lib/apis/memories';
	import { getFolders } from '$lib/apis/folders';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EditMemoryModal from './EditMemoryModal.svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import XMark from '$lib/components/icons/XMark.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';

	const i18n = getContext('i18n');
	dayjs.extend(localizedFormat);

	export let show = false;

	let memories = [];
	let allFolders = [];
	let loading = true;

	let query = '';
	let orderBy = 'updated_at';
	let direction = 'desc';

	// Tabs: 'global' | 'folders'
	let activeTab = 'global';
	let selectedFolderId: string | null = null;

	// Category collapse state
	let collapsedCategories: Record<string, boolean> = {};

	const setSortKey = (key: string) => {
		if (orderBy === key) {
			direction = direction === 'asc' ? 'desc' : 'asc';
		} else {
			orderBy = key;
			direction = 'asc';
		}
	};

	let showAddMemoryModal = false;
	let showEditMemoryModal = false;
	let addMemoryCategory = '';
	let addMemoryFolderId: string | null = null;

	let selectedMemory = null;

	let showClearConfirmDialog = false;
	let clearScope: 'all' | 'category' | 'folder' = 'all';
	let clearTargetId: string = '';
	let showDeleteConfirm = false;

	// ── Tag parsing helpers ──

	const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
		IDENTITY: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-300', border: 'border-blue-200 dark:border-blue-800' },
		USER: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-300', border: 'border-emerald-200 dark:border-emerald-800' },
		FEEDBACK: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300', border: 'border-amber-200 dark:border-amber-800' },
		PROJECT: { bg: 'bg-purple-100 dark:bg-purple-900/40', text: 'text-purple-700 dark:text-purple-300', border: 'border-purple-200 dark:border-purple-800' },
		LOCAL: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-500 dark:text-gray-400', border: 'border-gray-200 dark:border-gray-700' },
	};

	const CATEGORY_LABELS: Record<string, string> = {
		IDENTITY: '🪪 Identity',
		USER: '⚙️ Preferences',
		FEEDBACK: '📏 Behavioral Rules',
		PROJECT: '📁 Project',
	};

	function parseTag(content: string): { baseCategory: string; fullTag: string; folderId: string | null; chatId: string | null; fact: string } {
		const match = content.match(/^\[([A-Z]+)(?::([^\]]+))?\]\s*/);
		if (!match) return { baseCategory: '', fullTag: '', folderId: null, chatId: null, fact: content };

		const baseCategory = match[1];
		const suffix = match[2] || '';
		const fullTag = match[0].trim();
		const fact = content.slice(match[0].length).replace(/\[[A-Z]+(?::[^\]]+)?\]/g, '').trim();

		let folderId: string | null = null;
		let chatId: string | null = null;

		if (suffix.startsWith('folder:')) {
			folderId = suffix.replace('folder:', '');
		} else if (suffix.startsWith('chat:')) {
			chatId = suffix.replace('chat:', '');
		}

		return { baseCategory, fullTag, folderId, chatId, fact };
	}

	function getCategoryColor(cat: string) {
		return CATEGORY_COLORS[cat] || CATEGORY_COLORS['LOCAL'];
	}

	function getFolderName(folderId: string): string {
		const folder = allFolders.find((f: any) => f.id === folderId);
		return folder?.name || folderId.slice(0, 12) + '...';
	}

	// ── Filtering logic ──

	// Global memories: IDENTITY, USER, FEEDBACK, PROJECT (without :folder:)
	$: globalMemories = (memories || []).filter((m) => {
		const { baseCategory, folderId, chatId } = parseTag(m.content);
		if (!baseCategory || baseCategory === 'LOCAL') return false;
		if (chatId) return false;
		if (baseCategory === 'PROJECT' && folderId) return false;
		return true;
	});

	// Folder-specific memories for selected folder
	$: folderMemories = selectedFolderId
		? (memories || []).filter((m) => {
				const { baseCategory, folderId } = parseTag(m.content);
				return baseCategory === 'PROJECT' && folderId === selectedFolderId;
			})
		: [];

	// Folders that have memories
	$: foldersWithMemories = (() => {
		const folderIds = new Set<string>();
		(memories || []).forEach((m) => {
			const { baseCategory, folderId } = parseTag(m.content);
			if (baseCategory === 'PROJECT' && folderId) {
				folderIds.add(folderId);
			}
		});
		return folderIds;
	})();

	// Combined folder list: folders with memories + all known folders
	$: folderList = (() => {
		const map = new Map<string, { id: string; name: string; count: number }>();
		// Known folders from API
		allFolders.forEach((f: any) => {
			map.set(f.id, { id: f.id, name: f.name, count: 0 });
		});
		// Add any folders that only exist in memories
		foldersWithMemories.forEach((fid) => {
			if (!map.has(fid)) {
				map.set(fid, { id: fid, name: fid.slice(0, 12) + '...', count: 0 });
			}
		});
		// Count memories per folder
		(memories || []).forEach((m) => {
			const { baseCategory, folderId } = parseTag(m.content);
			if (baseCategory === 'PROJECT' && folderId && map.has(folderId)) {
				map.get(folderId)!.count++;
			}
		});
		return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
	})();

	// Active memories for current view
	$: activeMemories = activeTab === 'global' ? globalMemories : folderMemories;

	// Search filter
	$: filteredMemories = query
		? activeMemories.filter((m) => m.content?.toLowerCase().includes(query.toLowerCase()))
		: activeMemories;

	// Sort
	$: sortedMemories = [...filteredMemories].sort((a, b) => {
		let aVal, bVal;
		if (orderBy === 'content') {
			aVal = (a.content ?? '').toLowerCase();
			bVal = (b.content ?? '').toLowerCase();
		} else {
			aVal = a.updated_at ?? 0;
			bVal = b.updated_at ?? 0;
		}
		if (direction === 'asc') return aVal > bVal ? 1 : -1;
		return aVal < bVal ? 1 : -1;
	});

	// Group by category (for global view)
	$: groupedMemories = (() => {
		if (activeTab !== 'global') return {};
		const groups: Record<string, typeof sortedMemories> = {};
		const categoryOrder = ['FEEDBACK', 'IDENTITY', 'USER', 'PROJECT'];
		categoryOrder.forEach((c) => (groups[c] = []));
		sortedMemories.forEach((m) => {
			const { baseCategory } = parseTag(m.content);
			if (groups[baseCategory] !== undefined) {
				groups[baseCategory].push(m);
			}
		});
		return groups;
	})();

	let onClearConfirmed = async () => {
		if (clearScope === 'all') {
			const res = await deleteMemoriesByUserId(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (res && memories.length > 0) {
				toast.success($i18n.t('All memories cleared successfully'));
				memories = [];
			}
			showClearConfirmDialog = false;
		} else {
			// Targeted deletion
			const idsToDelete = (memories || []).filter((m) => {
				const { baseCategory, folderId } = parseTag(m.content);
				if (clearScope === 'category') {
					return baseCategory === clearTargetId;
				} else if (clearScope === 'folder') {
					return baseCategory === 'PROJECT' && folderId === clearTargetId;
				}
				return false;
			}).map((m) => m.id);

			if (idsToDelete.length === 0) {
				toast.error($i18n.t('No memories found to clear'));
				showClearConfirmDialog = false;
				return;
			}

			loading = true;
			showClearConfirmDialog = false;
			let successCount = 0;
			for (const id of idsToDelete) {
				const res = await deleteMemoryById(localStorage.token, id).catch(() => null);
				if (res) successCount++;
			}
			if (successCount > 0) {
				toast.success($i18n.t(`Cleared ${successCount} memories`));
				const clearedSet = new Set(idsToDelete);
				memories = (memories || []).filter((m) => !clearedSet.has(m.id));
			}
			loading = false;
		}
	};

	function toggleCategory(cat: string) {
		collapsedCategories[cat] = !collapsedCategories[cat];
		collapsedCategories = collapsedCategories;
	}

	function handleAddMemory() {
		if (activeTab === 'folders' && selectedFolderId) {
			addMemoryCategory = 'PROJECT';
			addMemoryFolderId = selectedFolderId;
		} else {
			addMemoryCategory = '';
			addMemoryFolderId = null;
		}
		showAddMemoryModal = true;
	}

	$: if (show && memories.length === 0 && loading) {
		(async () => {
			memories = await getMemories(localStorage.token);
			try {
				allFolders = await getFolders(localStorage.token) || [];
			} catch {
				allFolders = [];
			}
			loading = false;
		})();
	}
</script>

<Modal size="lg" bind:show>
	<div>
		<!-- Header -->
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class="flex items-center gap-2">
				<div class="text-lg font-medium">{$i18n.t('Memory Manager')}</div>

				{#if !loading}
					<div class="text-sm font-medium text-gray-400 dark:text-gray-500">
						{memories.filter((m) => parseTag(m.content).baseCategory !== 'LOCAL').length}
					</div>
				{/if}
			</div>

			<button class="self-center" on:click={() => (show = false)}>
				<XMark className="size-5" />
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<!-- Tabs -->
			<div class="flex gap-1 mb-3 border-b border-gray-100 dark:border-gray-800">
				<button
					class="flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors rounded-t-lg {activeTab === 'global'
						? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400 -mb-px'
						: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
					on:click={() => {
						activeTab = 'global';
						selectedFolderId = null;
						query = '';
					}}
				>
					<GlobeAlt className="size-4" />
					{$i18n.t('Global')}
					{#if !loading}
						<span class="text-xs text-gray-400 dark:text-gray-500 ml-0.5">({globalMemories.length})</span>
					{/if}
				</button>

				<button
					class="flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors rounded-t-lg {activeTab === 'folders'
						? 'text-purple-600 dark:text-purple-400 border-b-2 border-purple-600 dark:border-purple-400 -mb-px'
						: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
					on:click={() => {
						activeTab = 'folders';
						query = '';
					}}
				>
					<Folder className="size-4" />
					{$i18n.t('Folders')}
					{#if !loading}
						<span class="text-xs text-gray-400 dark:text-gray-500 ml-0.5">({foldersWithMemories.size})</span>
					{/if}
				</button>
			</div>

			{#if activeTab === 'folders'}
				<!-- Folders layout: sidebar + content -->
				<div class="flex gap-3 min-h-[20rem]">
					<!-- Folder sidebar -->
					<div class="w-44 shrink-0 border-r border-gray-100 dark:border-gray-800 pr-3 overflow-y-auto max-h-[28rem]">
						{#if folderList.length === 0}
							<div class="text-xs text-gray-400 dark:text-gray-500 py-4 text-center">
								{$i18n.t('No folders')}
							</div>
						{:else}
							{#each folderList as folder (folder.id)}
								<button
									class="w-full text-left px-2 py-1.5 text-sm rounded-lg mb-0.5 transition-colors flex items-center justify-between {selectedFolderId === folder.id
										? 'bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300'
										: 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-850'}"
									on:click={() => {
										selectedFolderId = folder.id;
										query = '';
									}}
								>
									<span class="truncate text-xs">{folder.name}</span>
									{#if folder.count > 0}
										<span class="text-[0.65rem] text-gray-400 dark:text-gray-500 shrink-0 ml-1">{folder.count}</span>
									{/if}
								</button>
							{/each}
						{/if}
					</div>

					<!-- Folder content -->
					<div class="flex-1 min-w-0">
						{#if !selectedFolderId}
							<div class="flex items-center justify-center h-full text-sm text-gray-400 dark:text-gray-500">
								← {$i18n.t('Select a folder')}
							</div>
						{:else}
							<!-- Search -->
							<div class="flex flex-1 items-center w-full mb-2">
								<div class="self-center ml-1 mr-3">
									<Search className="size-3.5" />
								</div>
								<input
									class="w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
									bind:value={query}
									placeholder={$i18n.t('Search memories...')}
									maxlength="500"
								/>
								{#if query}
									<button
										class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
										on:click={() => (query = '')}
									>
										<XMark className="size-3" strokeWidth="2" />
									</button>
								{/if}
							</div>

							<!-- Folder memory list -->
							<div class="text-left text-sm w-full max-h-[24rem] overflow-y-auto">
								{#if sortedMemories.length === 0}
									<div class="text-xs text-gray-400 dark:text-gray-500 text-center py-8">
										{$i18n.t('No memories in this folder')}
									</div>
								{:else}
									{#each sortedMemories as memory (memory.id)}
										{@const parsed = parseTag(memory.content)}
										<div
											class="w-full flex justify-between items-center rounded-xl text-sm py-2 px-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition cursor-pointer group"
											on:click={() => {
												selectedMemory = memory;
												showEditMemoryModal = true;
											}}
										>
											<div class="flex-1 min-w-0 pr-2">
												<div class="flex items-center gap-2">
													<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[0.6rem] font-semibold uppercase {getCategoryColor('PROJECT').bg} {getCategoryColor('PROJECT').text}">
														PROJECT
													</span>
													<span class="text-ellipsis line-clamp-1">{parsed.fact}</span>
												</div>
												<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
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
								{/if}
							</div>
						{/if}
					</div>
				</div>
			{:else}
				<!-- Global view -->
				<!-- Search -->
				<div class="flex flex-1 items-center w-full mb-2">
					<div class="self-center ml-1 mr-3">
						<Search className="size-3.5" />
					</div>
					<input
						class="w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={query}
						placeholder={$i18n.t('Search memories...')}
						maxlength="500"
					/>
					{#if query}
						<button
							class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
							on:click={() => (query = '')}
						>
							<XMark className="size-3" strokeWidth="2" />
						</button>
					{/if}
				</div>

				<!-- Grouped memory list -->
				<div class="flex flex-col w-full">
					{#if !loading}
						{#if sortedMemories.length === 0}
							<div class="text-xs text-gray-400 dark:text-gray-500 text-center px-5 min-h-20 w-full flex justify-center items-center">
								{#if memories.length === 0}
									{$i18n.t('Memories accessible by LLMs will be shown here.')}
								{:else}
									{$i18n.t('No results found')}
								{/if}
							</div>
						{:else if query}
							<!-- Flat list when searching -->
							<div class="text-left text-sm w-full max-h-[28rem] overflow-y-auto">
								{#each sortedMemories as memory (memory.id)}
									{@const parsed = parseTag(memory.content)}
									{@const colors = getCategoryColor(parsed.baseCategory)}
									<div
										class="w-full flex justify-between items-center rounded-xl text-sm py-2 px-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition cursor-pointer group"
										on:click={() => {
											selectedMemory = memory;
											showEditMemoryModal = true;
										}}
									>
										<div class="flex-1 min-w-0 pr-2">
											<div class="flex items-center gap-2">
												<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[0.6rem] font-semibold uppercase {colors.bg} {colors.text} shrink-0">
													{parsed.baseCategory}
												</span>
												<span class="text-ellipsis line-clamp-1">{parsed.fact}</span>
											</div>
											<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
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
						{:else}
							<!-- Grouped view by category -->
							<div class="text-left text-sm w-full max-h-[28rem] overflow-y-auto space-y-1">
								{#each Object.entries(groupedMemories) as [category, mems] (category)}
									{#if mems.length > 0}
										{@const colors = getCategoryColor(category)}
										<div class="rounded-xl overflow-hidden">
											<!-- Category header -->
											<!-- svelte-ignore a11y-click-events-have-key-events // svelte-ignore a11y-interactive-supports-focus -->
											<div
												class="group w-full flex items-center justify-between px-3 py-2 {colors.bg} hover:opacity-90 transition-opacity cursor-pointer"
												on:click={() => toggleCategory(category)}
												role="button"
											>
												<div class="flex items-center gap-2">
													<span class="text-xs font-semibold {colors.text}">
														{CATEGORY_LABELS[category] || category}
													</span>
													<span class="text-[0.6rem] {colors.text} opacity-60">{mems.length}</span>
												</div>
												<div class="flex items-center gap-3 {colors.text}">
													<!-- Don't bubble up click so it doesn't toggle accordion -->
													<div class="opacity-0 group-hover:opacity-100 transition-opacity" on:click|stopPropagation>
														<Tooltip content={$i18n.t('Clear Category')}>
															<button
																class="p-1 hover:bg-black/10 dark:hover:bg-white/10 rounded-md transition"
																on:click={() => {
																	clearScope = 'category';
																	clearTargetId = category;
																	showClearConfirmDialog = true;
																}}
															>
																<GarbageBin className="size-3" strokeWidth="1.5" />
															</button>
														</Tooltip>
													</div>
													{#if collapsedCategories[category]}
														<ChevronDown className="size-3" />
													{:else}
														<ChevronUp className="size-3" />
													{/if}
												</div>
											</div>

											<!-- Category memories -->
											{#if !collapsedCategories[category]}
												<div class="border-x border-b {colors.border} rounded-b-xl">
													{#each mems as memory (memory.id)}
														{@const parsed = parseTag(memory.content)}
														<div
															class="w-full flex justify-between items-center text-sm py-2 px-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition cursor-pointer group border-b last:border-0 border-gray-50 dark:border-gray-800/50"
															on:click={() => {
																selectedMemory = memory;
																showEditMemoryModal = true;
															}}
														>
															<div class="flex-1 min-w-0 pr-2">
																<div class="text-ellipsis line-clamp-1">{parsed.fact}</div>
																<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
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
										</div>
									{/if}
								{/each}
							</div>
						{/if}
					{:else}
						<div class="w-full flex justify-center items-center min-h-20">
							<Spinner className="size-4" />
						</div>
					{/if}
				</div>
			{/if}

			<!-- Footer -->
			<div class="flex justify-between items-center text-sm mt-3 pt-2 border-t border-gray-100 dark:border-gray-800">
				<div class="flex gap-2">
					<button
						class="px-2 py-1 text-xs text-gray-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 hover:underline transition"
						disabled={memories.length === 0}
						on:click={() => {
							clearScope = 'all';
							showClearConfirmDialog = true;
						}}
					>
						{$i18n.t('Clear all memory')}
					</button>

					{#if activeTab === 'folders' && selectedFolderId}
						<button
							class="px-2 py-1 text-xs text-gray-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 hover:underline transition border-l border-gray-200 dark:border-gray-800 pl-3"
							disabled={folderMemories.length === 0}
							on:click={() => {
								clearScope = 'folder';
								clearTargetId = selectedFolderId;
								showClearConfirmDialog = true;
							}}
						>
							{$i18n.t('Clear folder memory')}
						</button>
					{/if}
				</div>

				<button
					class="px-3 py-1.5 bg-black hover:bg-gray-900 text-white dark:bg-white dark:hover:bg-gray-100 dark:text-black transition rounded-full flex items-center gap-2"
					on:click={handleAddMemory}
				>
					<Plus className="size-3.5" />
					{$i18n.t('Add Memory')}
				</button>
			</div>
		</div>
	</div>
</Modal>

<ConfirmDialog
	title={clearScope === 'all' 
		? $i18n.t('Clear All Memories') 
		: clearScope === 'category' 
			? $i18n.t('Clear Category') 
			: $i18n.t('Clear Folder')}
	message={clearScope === 'all' 
		? $i18n.t('Are you sure you want to clear all memories? This action cannot be undone.') 
		: $i18n.t('Are you sure you want to clear these specific memories? This action cannot be undone.')}
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
			memories = await getMemories(localStorage.token);
		}
		showDeleteConfirm = false;
	}}
	on:cancel={() => {
		showDeleteConfirm = false;
	}}
>
	<div class=" text-sm text-gray-500 flex-1">
		{$i18n.t('Are you sure you want to delete this memory? This action cannot be undone.')}
		<div
			class=" mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded-xl border border-gray-100 dark:border-gray-800 text-black dark:text-white whitespace-pre-wrap break-words max-h-32 overflow-y-auto"
		>
			{selectedMemory?.content}
		</div>
	</div>
</ConfirmDialog>

<AddMemoryModal
	bind:show={showAddMemoryModal}
	category={addMemoryCategory}
	folderId={addMemoryFolderId}
	on:save={async () => {
		memories = await getMemories(localStorage.token);
	}}
/>

<EditMemoryModal
	bind:show={showEditMemoryModal}
	memory={selectedMemory}
	on:save={async () => {
		memories = await getMemories(localStorage.token);
	}}
/>
