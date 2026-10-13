import { mountDiagnostics } from './diagnostics.js';
import { mountInstall } from './install.js';
// Successor tickets export a mount(root, api) page from their own module and append one entry.
import { mountSkill } from './skill.js';
import { mountCredentials } from './credentials.js';
export const pages = [{ id: 'diagnostics', label: '概览与测试', number: '01', mount: mountDiagnostics }];
pages.push({ id: 'install', label: '安装 CLI', number: '02', mount: mountInstall });
pages.push({ id: 'skill', label: 'Claude Code Skill', number: '03', mount: mountSkill });
pages.push({ id: 'credentials', label: 'Tavily 凭据', number: '04', mount: mountCredentials });
import { mountSources } from './sources.js';
pages.push({ id: 'sources', label: '搜索源', number: '05', mount: mountSources });
import { mountSettings } from './settings.js';
pages.push({ id: 'settings', label: '搜索设置', number: '05B', mount: mountSettings });
import { mountMigration } from './migration.js';
pages.push({ id: 'migration', label: '旧配置迁移', number: '09', mount: mountMigration });
