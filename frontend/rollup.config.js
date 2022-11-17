import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import terser from "@rollup/plugin-terser";
import postcss from 'rollup-plugin-postcss';
import postcssLogical from 'postcss-logical';
import autoprefixer from 'autoprefixer';
import replace from '@rollup/plugin-replace';
import copy from 'rollup-plugin-copy'
import {getBabelOutputPlugin} from '@rollup/plugin-babel';

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
        postcssLogical(),
        autoprefixer(),
      ]
    }),
    copy({
        targets: [
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-400-normal.woff*', dest: '../app/static/fonts' },
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-700-normal.woff*', dest: '../app/static/fonts' },
        ]
    }),
    !dev && getBabelOutputPlugin({
        compact: false,
        presets: [[
            '@babel/preset-env', {
                loose: true,
                bugfixes: true,
                modules: false,
                targets: {
                    esmodules: true
                }
            }
        ]],
    }),
    !dev && terser(),
  ],
};
