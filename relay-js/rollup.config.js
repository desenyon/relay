import typescript from '@rollup/plugin-typescript';

const external = [];

/** @type {import('rollup').RollupOptions[]} */
export default [
  // ESM build
  {
    input: 'src/index.ts',
    output: {
      file: 'dist/relay.esm.js',
      format: 'esm',
      sourcemap: true,
    },
    external,
    plugins: [
      typescript({
        tsconfig: './tsconfig.json',
        declaration: true,
        declarationDir: 'dist',
      }),
    ],
  },
  // CJS build
  {
    input: 'src/index.ts',
    output: {
      file: 'dist/relay.cjs.js',
      format: 'cjs',
      sourcemap: true,
      exports: 'named',
    },
    external,
    plugins: [
      typescript({
        tsconfig: './tsconfig.json',
        declaration: false,
      }),
    ],
  },
];
