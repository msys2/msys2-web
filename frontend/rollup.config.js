import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import {terser} from "rollup-plugin-terser";
import postcss from 'rollup-plugin-postcss';
import autoprefixer from 'autoprefixer';
import replace from '@rollup/plugin-replace';
import copy from 'rollup-plugin-copy'

const dev = process.env.ROLLUP_WATCH === 'true';

export default {
  input: 'index.js',
  output: {
    file: '../app/static/index.js',
    format: 'es',
  },
  plugins: [
    resolve(),
    commonjs(),
    replace({
        preventAssignment: true,
        'process.env.NODE_ENV': JSON.stringify('production'),
    }),
    postcss({
      extract: 'index.css',
      minimize: true,
      plugins: [
        autoprefixer()
      ]
    }),
    copy({
        targets: [
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-400-normal.woff*', dest: '../app/static/fonts' },
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-700-normal.woff*', dest: '../app/static/fonts' },
        ]
    }),
    !dev && terser(),
  ],
};
