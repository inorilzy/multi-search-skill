import { mountDiagnostics } from './diagnostics.js';
// Successor tickets export a mount(root, api) page from their own module and append one entry.
export const pages = [{ id: 'diagnostics', label: '概览与测试', number: '01', mount: mountDiagnostics }];
