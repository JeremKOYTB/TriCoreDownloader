def _convert_markdown_to_html(self, text):
        if not text:
            return ""
        
        lines = text.split("\n")
        html_lines = []
        in_code = False
        in_list = False
        in_blockquote = False
        
        for line in lines:
            line_str = line.strip()
            
            if line_str.startswith("```"):
                if in_code:
                    html_lines.append("</pre></div>")
                    in_code = False
                else:
                    html_lines.append("<div style='background-color: #2D2D36; padding: 8px; border-radius: 6px; margin: 6px 0;'><pre style='margin: 0; color: #E8E8E8; font-family: Consolas, monospace; white-space: pre-wrap;'>")
                    in_code = True
                continue
                
            if in_code:
                escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                html_lines.append(escaped + "\n")
                continue
                
            if not line_str:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                if in_blockquote:
                    html_lines.append("</blockquote>")
                    in_blockquote = False
                html_lines.append("<br>")
                continue
                
            if line_str.startswith(">"):
                line_str = line_str.lstrip(">").strip()
                if not in_blockquote:
                    html_lines.append("<blockquote style='color: #A0A0AB; font-style: italic; margin: 4px 0; padding-left: 10px; border-left: 3px solid #4A4A55;'>")
                    in_blockquote = True
            else:
                if in_blockquote:
                    html_lines.append("</blockquote>")
                    in_blockquote = False
                    
            is_list_item = False
            if line_str.startswith("- ") or line_str.startswith("* "):
                is_list_item = True
                line_str = line_str[2:].strip()
                if not in_list:
                    html_lines.append("<ul style='margin-top: 4px; margin-bottom: 4px; padding-left: 20px;'>")
                    in_list = True
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                    
            is_header = False
            header_match = re.match(r'^(#{1,6})\s+(.*)', line_str)
            if header_match:
                is_header = True
                level = len(header_match.group(1))
                line_str = header_match.group(2).strip()
                
                size_map = {1: "18pt", 2: "15pt", 3: "13pt", 4: "11pt", 5: "10pt", 6: "9pt"}
                margin_top = "12px" if level <= 3 else "8px"
                header_open = f"<div style='color: #FFFFFF; font-size: {size_map.get(level, '11pt')}; font-weight: bold; margin-top: {margin_top}; margin-bottom: 6px;'>"
                header_close = "</div>"
                
            line_str = re.sub(r'`(.*?)`', r'<code style="background-color: #2D2D36; padding: 2px 4px; border-radius: 4px; color: #C4A1FF;">\1</code>', line_str)
            line_str = re.sub(r'\*\*(.*?)\*\*', r'<b style="color: #FFFFFF;">\1</b>', line_str)
            line_str = re.sub(r'(?<!\w)__(.*?)__(?!\w)', r'<b style="color: #FFFFFF;">\1</b>', line_str)
            line_str = re.sub(r'\*(.*?)\*', r'<i style="color: #E8E8E8;">\1</i>', line_str)
            line_str = re.sub(r'(?<!\w)_(.*?)_(?!\w)', r'<i style="color: #E8E8E8;">\1</i>', line_str)
            line_str = re.sub(r'~~(.*?)~~', r'<s style="color: #8A8A95;">\1</s>', line_str)
            line_str = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color: #00A2E8; text-decoration: none;">\1</a>', line_str)
            
            if is_header:
                html_lines.append(f"{header_open}{line_str}{header_close}")
            elif is_list_item:
                html_lines.append(f"<li>{line_str}</li>")
            else:
                html_lines.append(f"<div>{line_str}</div>")
                
        if in_list:
            html_lines.append("</ul>")
        if in_blockquote:
            html_lines.append("</blockquote>")
        if in_code:
            html_lines.append("</pre></div>")
            
        return "".join(html_lines)
