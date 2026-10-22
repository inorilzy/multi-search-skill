import { mountDiagnostics } from './diagnostics.js';
import { mountInstall } from './install.js';
// Successor tickets export a mount(root, api) page from their own module and append one entry.
import { mountSkill } from './skill.js';
export const pages = [{ id: 'diagnostics', label: '概览与测试', number: '01', mount: mountDiagnostics }];
pages.push({ id: 'install', label: '安装 CLI', number: '02', mount: mountInstall });
pages.push({ id: 'skill', label: 'Claude Code Skill', number: '03', mount: mountSkill });
// Tavily is one of the sources managed on the sources page; it no longer owns a page of its own.
import { mountSources } from './sources.js';
pages.push({ id: 'sources', label: '搜索源与凭据', number: '04', mount: mountSources });
import { mountSettings } from './settings.js';
pages.push({ id: 'settings', label: '搜索设置', number: '05', mount: mountSettings });
import { mountScrape } from './scrape.js';
pages.push({ id: 'scrape', label: '抓取设置', number: '06', mount: mountScrape });
