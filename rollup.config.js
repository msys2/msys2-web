import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import {terser} from "rollup-plugin-terser";
import postcss from 'rollup-plugin-postcss';
import autoprefixer from 'autoprefixer';

const dev = process.env.ROLLUP_WATCH === 'true';

export default {
  input: 'index.js',
  output: {
    file: 'app/static/index.js',
    format: 'iife'
  },
  plugins: [
    resolve(),
    commonjs(),
    postcss({
      extract: 'index.css',
      minimize: true,
      plugins: [
        autoprefixer()
      ]
    }),
    !dev && terser(),
  ],
};
