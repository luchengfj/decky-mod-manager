// Aligned with the LOCKED decky-plugin-template commit
// 90d0780e882a17f5714fc6de044c645f22608290, whose rollup.config.js is exactly
// `import deckyPlugin from "@decky/rollup"; export default deckyPlugin({});`.
// @decky/rollup 1.0.2 produces the ESM + SP_REACT/SP_JSX/DFL globals shape that
// Decky Loader v3.3.1 actually loads (verified against 5 installed plugins on
// the device). A hand-written CJS config was NOT loadable — see VERIFICATION.md V6.
import deckyPlugin from '@decky/rollup';

export default deckyPlugin({});
