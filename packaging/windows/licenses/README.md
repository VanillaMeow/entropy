# Third-party licenses

Entropy's application source is licensed under the Mozilla Public License 2.0;
its full text is installed as `LICENSE` in the application directory.

The bundled Qt libraries, PySide6 and shiboken6 are copyright The Qt Company Ltd.
and other contributors, and are distributed under the GNU Lesser General Public
License version 3. Its text and the GNU General Public License version 3, which
it incorporates, are included in `Qt/`. Qt and PySide6 remain separate shared
libraries in the installed application. Source and licensing information:

- https://code.qt.io/cgit/qt/
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://www.qt.io/licensing/open-source-lgpl-obligations

MNN is copyright Alibaba Group Holding Limited and its contributors, and is
licensed under Apache License 2.0. `MNN/LICENSE` is copied from the pinned MNN
3.6.2 source revision used by the build:
https://github.com/alibaba/MNN/tree/7e3c6fb5225d3ccf22807ee641332669df34650d

The Qt license texts are from the SPDX license list v3.27.0:
https://github.com/spdx/license-list-data/tree/v3.27.0/text

The Real-ESRGAN model's BSD 3-Clause license is installed beside the model in
`models/` and is also shown on the installer's license page. Other dependencies'
license and notice files are collected from their installed distributions into
the corresponding directories here. `METADATA` files preserve the distributions'
version, author, license and source information where provided.
