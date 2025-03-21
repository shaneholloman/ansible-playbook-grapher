# Copyright (C) 2024 Mohamed El Mouctar HAIDARA
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from pathlib import Path

from ansible.utils.display import Display
from lxml import etree
from svg.path import parse_path

from ansibleplaybookgrapher.graph_model import PlaybookNode

display = Display()

JQUERY = "https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def _read_data(filename: str) -> str:
    """Read the script and return is as string
    :param filename:
    :return:
    """
    current_dir = Path(__file__).parent.resolve()
    javascript_path = current_dir / "../../data" / filename

    with javascript_path.open() as javascript:
        return javascript.read()


class GraphvizPostProcessor:
    """Post process the svg by adding some javascript, css and hover effects."""

    def __init__(self, svg_path: str) -> None:
        """:param svg_path:"""
        self.svg_path = svg_path
        self.tree = etree.parse(svg_path)
        self.root = self.tree.getroot()

    def insert_script_tag(self, index: int, attrib: dict) -> None:
        """:param index:
        :param attrib:
        :return:
        """
        element_script_tag = etree.Element("script", attrib=attrib)

        self.root.insert(index, element_script_tag)

    def insert_cdata(self, index: int, tag: str, attrib: dict, cdata_text: str) -> None:
        """Insert cdata in the SVG
        :param index:
        :param tag:
        :param attrib:
        :param cdata_text:
        :return:
        """
        element = etree.Element(tag, attrib=attrib)
        element.text = etree.CDATA(cdata_text)

        self.root.insert(index, element)

    def post_process(
        self,
        playbook_nodes: list[PlaybookNode] | None = None,
        *args,
        **kwargs,
    ) -> None:
        """:param playbook_nodes:
        :param args:
        :param kwargs:
        :return:
        """
        self.root.set("id", "svg")

        # insert jquery
        self.insert_script_tag(
            0,
            attrib={"type": "text/javascript", "href": JQUERY, "id": "jquery"},
        )

        # insert my javascript
        self.insert_cdata(
            1,
            "script",
            attrib={"type": "text/javascript", "id": "my_javascript"},
            cdata_text=_read_data("highlight-hover.js"),
        )

        # insert my css
        self.insert_cdata(
            2,
            "style",
            attrib={"type": "text/css", "id": "my_css"},
            cdata_text=_read_data("graph.css"),
        )

        # Curve the text on the edges
        self._curve_text_on_edges()

        playbook_nodes = playbook_nodes or []
        for p_node in playbook_nodes:
            # Insert the graph representation for the links between the nodes
            self._insert_links(p_node)

    def write(self, output_filename: str | None = None) -> None:
        """Write the svg in the given filename
        :param output_filename:
        :return:
        """
        if output_filename is None:
            output_filename = self.svg_path

        self.tree.write(output_filename, xml_declaration=True, encoding="UTF-8")

    def _insert_links(self, playbook_node: PlaybookNode) -> None:
        """Insert the links between nodes in the SVG file.

        :param playbook_node: One of the playbooks in the svg.
        """
        display.vv(f"Inserting links structure for the playbook '{playbook_node.name}'")
        links_structure = playbook_node.get_links_structure()

        for node, node_links in links_structure.items():
            # Find the group g with the specified id
            xpath_result = self.root.xpath(
                f"ns:g/*[@id='{node.id}']",
                namespaces={"ns": SVG_NAMESPACE},
            )
            if xpath_result:
                element = xpath_result[0]
                links = etree.Element("links")
                for counter, link in enumerate(node_links, 1):
                    links.append(
                        etree.Element(
                            "link",
                            attrib={
                                "target": link.id,
                                "edge": f"edge_{node.id}-{link.id}",
                            },
                        ),
                    )

                element.append(links)

    def _get_text_path_start_offset(self, path_element, text: str) -> str:  # noqa: ANN001
        """Get the start offset where the edge label should begin
        :param path_element:
        :param text:
        :return:
        """
        # Get Bézier curve
        path_segments = parse_path(path_element.get("d"))
        # The segments usually contain 3 elements: One MoveTo and one or two CubicBezier objects.
        # This is relatively slow to compute. Decreasing the "error" will drastically slow down the post-processing
        segment_length = path_segments.length(error=1e-4)
        text_length = len(text)
        # We put the label closer to the target node
        offset_factor = 0.76

        start_offset = segment_length * offset_factor - text_length
        msg = f"{len(path_segments)} segment(s) found for the path '{path_element.get('id')}', "
        msg += f"segment_length={segment_length}, start_offset={start_offset}, text_length={text_length}"
        display.vvvvv(msg)
        return str(start_offset)

    def _curve_text_on_edges(self) -> None:
        """Update the text on each edge to curve it based on the edge
        :return:
        """
        # Fetch all edges
        edge_elements = self.root.xpath(
            "ns:g/*[starts-with(@id,'edge_')]",
            namespaces={"ns": SVG_NAMESPACE},
        )

        for edge in edge_elements:
            text_element = edge.find(".//text", namespaces=self.root.nsmap)

            # Define an ID for the path so that we can reference it explicitly
            path_id = f"path_{edge.get('id')}"

            path_element = edge.find(".//path", namespaces=self.root.nsmap)
            path_element.set("id", path_id)

            # Create a curved textPath: the text will follow the path
            text_path = etree.Element("textPath")
            text_path.set("{http://www.w3.org/1999/xlink}href", f"#{path_id}")
            text_path.text = text_element.text

            offset = self._get_text_path_start_offset(path_element, text_path.text)
            text_path.set("startOffset", offset)

            text_element.append(text_path)

            dy = -0.2
            text_element.set("dy", f"{dy}%")
            # Remove unnecessary attributes and clear the text
            text_element.attrib.pop("x", "")
            text_element.attrib.pop("y", "")
            text_element.text = None
