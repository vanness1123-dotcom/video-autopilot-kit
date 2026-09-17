"""Bounded measured text layout inside an immutable preferred container.

No media geometry, collision, rendering, or alternate placement is considered.
"""
from __future__ import annotations

import io
import math

from .typography import TypographyError, _dependencies, _digest, _finite, _integer, inspect_font

POLICY = "measured_lines.v1"
PUNCTUATION_POLICY = "bounded_cjk.v1"
FIT_POLICY = "discrete_100_95_90_85.v1"
SPACING_POLICY = "font_size_0.15.v1"
OPENING = frozenset("（「『《〈【〔([{“‘")
CLOSING = frozenset("）」』》〉】〕，。、！？：；)]},.!?:;”’…")
SCALES = (1.0, .95, .90, .85)
DEFAULT_LINES = {"title": 2, "location_label": 2, "section_label": 1,
                 "caption": 2, "closing_title": 2, "closing_subtitle": 2}
MINIMUM = {"title": 52, "closing_title": 52, "location_label": 32,
           "section_label": 32, "caption": 32, "closing_subtitle": 32}
ELLIPSIS_TYPES = frozenset({"section_label", "caption", "closing_subtitle"})
MAX_CHARACTERS = 256
EPS = 1e-9


class TypographyFitError(TypographyError):
    """Approved content cannot fit; caller may omit only this overlay."""


def _han(char):
    return 0x3400 <= ord(char) <= 0x9FFF or 0xF900 <= ord(char) <= 0xFAFF


def break_positions(text):
    """Indices in source text, preserving Latin tokens and bounded punctuation."""
    result = []
    for i in range(1, len(text)):
        if "\u00a0" in text[i-1:i+1]: continue
        left, right = text[:i].rstrip(), text[i:].lstrip()
        if not left or not right or left[-1] in OPENING or right[0] in CLOSING:
            continue
        # NBSP does not provide a break opportunity.
        space = (text[i-1].isspace() or text[i].isspace()) and "\u00a0" not in text[i-1:i+1]
        if space or _han(text[i-1]) or _han(text[i]):
            result.append(i)
    return result


def _span(text, start, end):
    while start < end and text[start].isspace(): start += 1
    while end > start and text[end-1].isspace(): end -= 1
    return [start, end]


def _inputs(overlay, base):
    kind = overlay.get("type")
    if kind not in DEFAULT_LINES: raise TypographyError("Unsupported text-layout Overlay type")
    placement = overlay.get("placement")
    if not isinstance(placement, dict): raise TypographyError("Text layout requires preferred container")
    container = {k: placement.get(k) for k in ("x", "y", "width", "height")}
    if not all(_finite(v) for v in container.values()): raise TypographyError("Invalid preferred container numerics")
    x,y,w,h = (container[k] for k in ("x","y","width","height"))
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1+EPS or y+h > 1+EPS:
        raise TypographyError("Preferred container outside canvas")
    style = overlay["style"]
    maximum = style.get("max_lines", DEFAULT_LINES[kind])
    if not _integer(maximum, 1) or maximum > DEFAULT_LINES[kind]:
        raise TypographyError("Unsupported max_lines for text type")
    alignment = style.get("alignment", placement.get("alignment"))
    if alignment not in ("left", "center", "right") or alignment != placement.get("alignment"):
        raise TypographyError("Inconsistent text alignment")
    return {"policy_version": POLICY, "punctuation_policy": PUNCTUATION_POLICY,
            "fitting_policy": FIT_POLICY, "spacing_policy": SPACING_POLICY,
            "preferred_container": container, "max_lines": maximum, "alignment": alignment,
            "ellipsis_allowed": kind in ELLIPSIS_TYPES,
            "minimum_font_size": math.ceil(MINIMUM[kind]*base["design_canvas"]["height"]/1920),
            "requested_font_size": base["resolved_font_size"]}


def _sizes(inputs):
    return list(dict.fromkeys(max(1, round(inputs["requested_font_size"]*s)) for s in SCALES
                             if max(1, round(inputs["requested_font_size"]*s)) >= inputs["minimum_font_size"]))


def layout_fingerprint(base, overlay, inputs):
    # Base fingerprint is the unchanged 11.4b-a metrics dependency projection.
    return _digest({"metrics_dependency": base["dependency_fingerprint"],
                    "content": overlay["content"]["text"], "type": overlay["type"], **inputs})


def _box(left, top, right, bottom, w, h):
    return {"x": left/w, "y": top/h, "width": (right-left)/w, "height": (bottom-top)/h}


def _union(boxes):
    left=min(b["x"] for b in boxes); top=min(b["y"] for b in boxes)
    right=max(b["x"]+b["width"] for b in boxes); bottom=max(b["y"]+b["height"] for b in boxes)
    return {"x":left,"y":top,"width":right-left,"height":bottom-top}


def _inside(box, container):
    return (box["x"] >= container["x"]-EPS and box["y"] >= container["y"]-EPS and
            box["x"]+box["width"] <= container["x"]+container["width"]+EPS and
            box["y"]+box["height"] <= container["y"]+container["height"]+EPS)


def _arrange(font, spans, text, ellipsis, inputs, canvas, size):
    w,h=canvas["width"],canvas["height"]; c=inputs["preferred_container"]
    x,y,cw,ch=c["x"]*w,c["y"]*h,c["width"]*w,c["height"]*h
    ascent,descent=font.getmetrics(); line_height=ascent+descent; gap=size*.15
    if len(spans)*line_height+(len(spans)-1)*gap > ch+EPS: return None
    rows=[]
    for index,(start,end) in enumerate(spans):
        display=text[start:end]+("…" if ellipsis and index==len(spans)-1 else "")
        if not display or display[0] in CLOSING or display[-1] in OPENING: return None
        advance=font.getlength(display); l,t,r,b=font.getbbox(display,anchor="ls")
        extent=max(advance,r)-min(0,l)
        if extent > cw+EPS or r<=l or b<=t: return None
        free=cw-extent; offset={"left":0,"center":free/2,"right":free}[inputs["alignment"]]
        bx=x+offset-min(0,l); by=y+ascent+index*(line_height+gap)
        ink=_box(bx+l,by+t,bx+r,by+b,w,h)
        advance_box=_box(bx,by-ascent,bx+advance,by+descent,w,h)
        if not _inside(ink,c) or not _inside(advance_box,c): return None
        rows.append({"text":display,"source_span":[start,end],"advance":advance/w,
                     "baseline_x":bx/w,"baseline_y":by/h,
                     "relative_ink_bounds":{"left":l/w,"top":t/h,"right":r/w,"bottom":b/h},
                     "ink_box":ink,"advance_box":advance_box})
    if any(a["ink_box"]["y"]+a["ink_box"]["height"] > b["ink_box"]["y"]+EPS for a,b in zip(rows,rows[1:])):
        return None
    return {"lines":rows,"ascent":ascent/h,"descent":descent/h,"line_height":line_height/h,
            "line_spacing":gap/h,"resolved_text_bounds":_union([r["ink_box"] for r in rows]),
            "layout_bounds":_union([r["advance_box"] for r in rows])}


def _wrap(font, text, end, ellipsis, inputs, canvas, size):
    # One line always wins if it fits. At most 255 two-line break candidates.
    whole=_span(text,0,end)
    result=_arrange(font,[whole],text,ellipsis,inputs,canvas,size)
    if result is not None: return result
    if inputs["max_lines"] == 1: return None
    candidates=[]
    for i in break_positions(text[:end]):
        spans=[_span(text,0,i),_span(text,i,end)]
        result=_arrange(font,spans,text,ellipsis,inputs,canvas,size)
        if result is None: continue
        widths=[r["advance"] for r in result["lines"]]
        imbalance=abs(widths[0]-widths[1])/max(widths)
        orphan=1 if min(widths)/max(widths)<.25 else 0
        candidates.append(((orphan,imbalance,i),result))
    return min(candidates,key=lambda c:c[0])[1] if candidates else None


def resolve_measured_layout(base, overlay, data):
    inputs=_inputs(overlay,base); text=overlay["content"]["text"]
    if len(text)>MAX_CHARACTERS: raise TypographyFitError("text_layout_character_limit")
    _,_,ImageFont,_=_dependencies(); sizes=_sizes(inputs)
    fonts={size:ImageFont.truetype(io.BytesIO(data),size,index=base["font_identity"]["face_index"],
                                 layout_engine=ImageFont.Layout.BASIC) for size in sizes}
    result=None; retained=len(text); ellipsis=False
    for size in sizes:
        result=_wrap(fonts[size],text,len(text),False,inputs,base["design_canvas"],size)
        if result is not None: break
    if result is None and sizes and inputs["ellipsis_allowed"]:
        coverage=inspect_font(data,base["font_identity"]["face_index"],text+"…")
        if not coverage["missing_codepoints"]:
            # At least 70% of non-space source characters survive; no word splitting.
            size=sizes[-1]
            for end in reversed(break_positions(text)):
                retained=_span(text,0,end)[1]
                if len(''.join(text[:retained].split())) < .7*len(''.join(text.split())): continue
                result=_wrap(fonts[size],text,retained,True,inputs,base["design_canvas"],size)
                if result is not None: ellipsis=True; break
    if result is None: raise TypographyFitError("text_does_not_fit_readable_size")
    display=''.join(r["text"] for r in result["lines"])
    if inspect_font(data,base["font_identity"]["face_index"],display)["missing_codepoints"]:
        raise TypographyError("Display glyph coverage failed")
    return {**inputs,**result,"resolved_font_size":size,"fit_scale":size/inputs["requested_font_size"],
            "size_step":sizes.index(size),"fit_reason":"ellipsis" if ellipsis else ("preferred_size" if size==inputs["requested_font_size"] else "bounded_reduction"),
            "ellipsis":ellipsis,"retained_source_end":retained,
            "dependency_fingerprint":layout_fingerprint(base,overlay,inputs),
            "validation":{"container_fit":True,"collision_checked":False,"display_coverage":"complete_unicode_cmap"}}


def validate_measured_layout(value, base, overlay):
    """Recompute composition/geometry facts; live font verification is separate."""
    def need(ok,message):
        if not ok: raise TypographyError(message)
    inputs=_inputs(overlay,base)
    expected=set(inputs)|{"lines","ascent","descent","line_height","line_spacing","resolved_text_bounds","layout_bounds",
                         "resolved_font_size","fit_scale","size_step","fit_reason","ellipsis","retained_source_end","dependency_fingerprint","validation"}
    need(isinstance(value,dict) and set(value)==expected,"Malformed measured layout")
    need(all(value[k]==v and type(value[k]) is type(v) for k,v in inputs.items()),"Stale/unsupported text-layout policy inputs")
    need(all(_finite(v) for v in value["preferred_container"].values()),"Invalid container numerics")
    sizes=_sizes(inputs); size=value["resolved_font_size"]
    need(_integer(size,1) and size in sizes,"Invalid readable font size")
    need(_integer(value["size_step"]) and value["size_step"]==sizes.index(size),"Invalid fitting step")
    need(_finite(value["fit_scale"]) and value["fit_scale"]==size/inputs["requested_font_size"],"Invalid fit scale")
    need(type(value["ellipsis"]) is bool and (not value["ellipsis"] or inputs["ellipsis_allowed"]),"Forbidden ellipsis")
    reason="ellipsis" if value["ellipsis"] else ("preferred_size" if size==inputs["requested_font_size"] else "bounded_reduction")
    need(value["fit_reason"]==reason,"Invalid fitting reason")
    text=overlay["content"]["text"]; end=value["retained_source_end"]
    need(_integer(end,1) and end<=len(text),"Invalid retained source boundary")
    if value["ellipsis"]:
        need(size==sizes[-1],"Ellipsis must follow the full bounded fitting ladder")
        need(end<len(text) and any(_span(text,0,i)[1]==end for i in break_positions(text)) and len(''.join(text[:end].split())) >= .7*len(''.join(text.split())),"Invalid ellipsis truncation")
    else: need(end==len(text),"Unapproved content truncation")
    rows=value["lines"]
    need(isinstance(rows,list) and 1<=len(rows)<=inputs["max_lines"],"Invalid measured line count")
    w,h=base["design_canvas"]["width"],base["design_canvas"]["height"]
    for key in ("ascent","descent","line_height","line_spacing"):
        need(_finite(value[key]) and value[key]>=0,"Invalid line metrics")
    need(value["ascent"]>0 and value["line_height"]>0 and abs(value["line_height"]-value["ascent"]-value["descent"])<EPS,"Invalid line height")
    need(abs(value["line_spacing"]-size*.15/h)<EPS,"Invalid line spacing")
    def box(b):
        need(isinstance(b,dict) and set(b)=={"x","y","width","height"} and all(_finite(v) for v in b.values()) and b["width"]>0 and b["height"]>0,"Invalid text box")
        need(_inside(b,inputs["preferred_container"]),"Text outside preferred container")
    def equal_box(a,b):
        box(a); need(all(abs(a[k]-b[k])<EPS for k in b),"Inconsistent text geometry")
    previous=0
    for i,row in enumerate(rows):
        need(isinstance(row,dict) and set(row)=={"text","source_span","advance","baseline_x","baseline_y","relative_ink_bounds","ink_box","advance_box"},"Malformed line")
        span=row["source_span"]
        need(isinstance(span,list) and len(span)==2 and all(_integer(n) for n in span) and previous<=span[0]<span[1]<=end,"Invalid source span")
        need(not text[previous:span[0]].strip(),"Dropped source content")
        if i:
            need(any(_span(text,0,j)[1]==previous and _span(text,j,end)[0]==span[0] for j in break_positions(text[:end])),"Illegal line break")
        display=text[span[0]:span[1]]+("…" if value["ellipsis"] and i==len(rows)-1 else "")
        need(row["text"]==display and display==display.strip() and display[0] not in CLOSING and display[-1] not in OPENING,"Invalid display composition/punctuation")
        previous=span[1]
        need(all(_finite(row[k]) for k in ("advance","baseline_x","baseline_y")) and row["advance"]>0,"Invalid baseline/advance")
        ink=row["relative_ink_bounds"]
        need(isinstance(ink,dict) and set(ink)=={"left","top","right","bottom"} and all(_finite(v) for v in ink.values()) and ink["right"]>ink["left"] and ink["bottom"]>ink["top"],"Invalid relative ink")
        c=inputs["preferred_container"]; extent=max(row["advance"],ink["right"])-min(0,ink["left"])
        offset={"left":0,"center":(c["width"]-extent)/2,"right":c["width"]-extent}[inputs["alignment"]]
        bx=c["x"]+offset-min(0,ink["left"]); by=c["y"]+value["ascent"]+i*(value["line_height"]+value["line_spacing"])
        need(abs(row["baseline_x"]-bx)<EPS and abs(row["baseline_y"]-by)<EPS,"Inconsistent aligned baseline")
        equal_box(row["ink_box"],{"x":bx+ink["left"],"y":by+ink["top"],"width":ink["right"]-ink["left"],"height":ink["bottom"]-ink["top"]})
        equal_box(row["advance_box"],{"x":bx,"y":by-value["ascent"],"width":row["advance"],"height":value["line_height"]})
        if i:
            for key in ("ink_box","advance_box"):
                need(rows[i-1][key]["y"]+rows[i-1][key]["height"]<=row[key]["y"]+EPS,"Overlapping text lines")
    need(not text[previous:end].strip(),"Dropped trailing content")
    equal_box(value["resolved_text_bounds"],_union([r["ink_box"] for r in rows]))
    equal_box(value["layout_bounds"],_union([r["advance_box"] for r in rows]))
    need(value["dependency_fingerprint"]==layout_fingerprint(base,overlay,inputs),"Stale text layout fingerprint")
    evidence=value["validation"]
    need(isinstance(evidence,dict) and set(evidence)=={"container_fit","collision_checked","display_coverage"} and evidence["container_fit"] is True and evidence["collision_checked"] is False and evidence["display_coverage"]=="complete_unicode_cmap","Invalid layout validation evidence")
