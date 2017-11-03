from falcon_kit.FastaReader import FastaReader
import logging
import re
import shlex
import subprocess

LOG = logging.getLogger(__name__)


def make_het_call(bam_fn, fasta_fn, vmap_fn, vpos_fn, q_id_map_fn, ctg_id):
    """samtools must be in $PATH.
    Writes into vmap_fn, vpos_fn, q_id_map_fn.
    """
    LOG.info('Getting ref_seq for {!r} in {!r}'.format(ctg_id, fasta_fn))
    for r in FastaReader(fasta_fn):
        rid = r.name.split()[0]
        if rid != ctg_id:
            continue
        ref_seq = r.sequence.upper()
        break
    else:
        ref_seq = ""
    LOG.info(' Length of ref_seq: {}'.format(len(ref_seq)))

    cmd = "samtools view %s %s" % (bam_fn, ctg_id)
    LOG.info('Capture `{}`'.format(cmd))
    p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)

    vmap_f = open(vmap_fn, "w")
    vpos_f = open(vpos_fn, "w")
    q_id_map_f = open(q_id_map_fn, "w")

    make_het_call_map(ref_seq, p.stdout, vmap_f, vpos_f, q_id_map_f)


def make_het_call_map(ref_seq, samtools_view_bam_ctg_f, vmap_f, vpos_f, q_id_map_f):
    """Given lines of samtools-view, lines of variant_map and variant_pos files, and a reference sequence,
    write into q_id_map, vmap, and vpos,

    q_id_map is
        q_id QNAME
        ...
    where q_id is 0, 1, 2, ...
    and QNAME is the first field of each line from samtools-view.
    """
    q_id_map = {}
    q_name_to_id = {}  # reverse of q_id_map
    pileup = {}
    q_max_id = 0
    q_id = 0
    cigar_re = re.compile(r"(\d+)([MIDNSHP=X])")

    for l in samtools_view_bam_ctg_f:
        l = l.strip().split()
        if l[0][0] == "@":
            continue

        QNAME = l[0]
        if QNAME not in q_name_to_id:
            q_id = q_max_id
            q_name_to_id[QNAME] = q_id
            q_max_id += 1

        q_id = q_name_to_id[QNAME]
        q_id_map[q_id] = QNAME
        FLAG = int(l[1])
        RNAME = l[2]
        POS = int(l[3]) - 1  # convert to zero base
        CIGAR = l[5]
        SEQ = l[9]
        rp = POS
        qp = 0

        skip_base = 0
        total_aln_pos = 0
        for m in cigar_re.finditer(CIGAR):
            adv = int(m.group(1))
            total_aln_pos += adv

            if m.group(2) == "S":
                skip_base += adv

        if total_aln_pos < 2000:
            continue
        if 1.0 - 1.0 * skip_base / total_aln_pos < 0.1:
            continue

        for m in cigar_re.finditer(CIGAR):
            adv = int(m.group(1))
            cigar_tag = m.group(2)
            if cigar_tag == "S":
                qp += adv
            elif cigar_tag in ("M", "=", "X"):
                matches = []
                for i in range(adv):
                    matches.append((rp, SEQ[qp]))
                    rp += 1
                    qp += 1
                for pos, b in matches:
                    pileup.setdefault(pos, {})
                    pileup[pos].setdefault(b, [])
                    pileup[pos][b].append(q_id)
            elif cigar_tag == "I":
                for i in range(adv):
                    qp += 1
            elif cigar_tag == "D":
                for i in range(adv):
                    rp += 1

        pos_k = pileup.keys()
        pos_k.sort()
        th = 0.25
        for pos in pos_k:
            if pos >= POS:
                break
            pupmap = pileup[pos]
            del pileup[pos]
            if len(pupmap) < 2:
                continue
            base_count = []
            total_count = 0
            for b in ["A", "C", "G", "T"]:
                count = len(pupmap.get(b, []))
                base_count.append((count, b))
                total_count += count
            if total_count < 10:
                continue

            base_count.sort()
            base_count.reverse()
            p0 = 1.0 * base_count[0][0] / total_count
            p1 = 1.0 * base_count[1][0] / total_count
            if p0 < 1.0 - th and p1 > th:
                b0 = base_count[0][1]
                b1 = base_count[1][1]
                ref_base = ref_seq[pos]
                print >> vpos_f, pos + 1, ref_base, total_count, " ".join(["%s %d" % (x[1], x[0]) for x in base_count])
                for q_id_ in pupmap[b0]:
                    print >> vmap_f, pos + 1, ref_base, b0, q_id_
                for q_id_ in pupmap[b1]:
                    print >> vmap_f, pos + 1, ref_base, b1, q_id_

    for q_id, q_name in q_id_map.items():
        print >> q_id_map_f, q_id, q_name


######
import argparse
import sys


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='make_het_call',  # better description?
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--ctg-id', required=True,
    )
    parser.add_argument(
        '--bam-fn', required=True,
    )
    parser.add_argument(
        '--fasta-fn', required=True,
    )
    parser.add_argument(
        '--vmap-fn', required=True,
        help='an output'
    )
    parser.add_argument(
        '--vpos-fn', required=True,
        help='an output'
    )
    parser.add_argument(
        '--q-id-map-fn', required=True,
        help='an output'
    )
    args = parser.parse_args(argv[1:])
    return args


def main(argv=sys.argv):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    make_het_call(**vars(args))


if __name__ == '__main__':  # pragma: no cover
    main()
