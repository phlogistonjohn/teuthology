#!/bin/bash
#
set -e -x

export TEUTHOLOGY_CONFIG=$PWD/.teuthology.yaml

SUITE=orch/cephadm/smb/
SUITE_ARGS=(--filter-out ubuntu,runc --filter deploy_smb_mgr_ctdb_res_dom)
BUILD_BRANCH=jjm-smb-ctdb-clustering
SUITE_BRANCH=jjm-smb-ctdb-clustering
DB_FILE=/home/jmulliga/tmp/teuthology/queue.db
OVERRIDES=/home/jmulliga/tmp/teuthology/overrides.yaml
BACKEND="sqlite://${DB_FILE}"
VENVDIR=_venv
MTYPE=oquack
VMS=(ceph0 ceph1 ceph2 ceph3 client dc0)

my_overrides() {
    cat <<EOF
overrides:
  cephadm:
    image: "quay.io/phlogistonjohn/ceph:dev"
    cephadm_from_container: true
  verify_ceph_hash: false
verify_ceph_hash: false
EOF
}

tcmd() {
    teuth_command="$1"
    if ! command -v "$teuth_command" >/dev/null; then
        echo "no ${teuth_command} found (need to activiate a virtual env?)"
        echo "   hint, try to run: . ${VENVDIR}/bin/activate"
        exit 2
    fi
    "$@"
}

machines_add_ceph_vms() {
    python -m teuthology.lock.sqlite_pool --rm-all
    cmd=(python -m teuthology.lock.sqlite_pool --machine-type="${MTYPE}")
    for h in "${VMS[@]}" ; do
        case "$h" in
            ceph*) : ;;
            *) continue ;;
        esac
        cmd+=(--add "${h}")
    done
    "${cmd[@]}" --list
}

machines_vm_revert() {
    for h in "${VMS[@]}" ; do
        virsh snapshot-revert --domain $h --snapshotname pre-bootstrap &
    done
    wait
}

keyzap() {
    for x in {200..210}; do
        ssh-keygen -R 192.168.76.$x || true
    done
}

for arg in "$@"; do
    echo "==> $arg"
    case "$arg" in
        --set=*)
            v="${arg/--set=/}"
            eval "$v"
            echo "$foo"
        ;;
        setup-virtual-env)
            test -d "${VENVDIR}" || python3 -m venv "${VENVDIR}"
            "${VENVDIR}/bin/pip" install -r requirements.txt
            "${VENVDIR}/bin/pip" install --require-virtualenv -e .
        ;;
        remove-virtual-env)
            rm -rf "${VENVDIR}"
        ;;
        veryclean)
            rm -rf ~/tmp/teuthology
        ;;
        clean)
            rm -rf "${DB_FILE}"  ~/tmp/teuthology/log/* ~/tmp/teuthology/archive/*
        ;;
        vm-revert)
            export LIBVIRT_DEFAULT_URI=qemu:///system
            machines_vm_revert
            machines_add_ceph_vms
        ;;
        vm-relearn)
            # tell teuthology the vms are available even if they are not
            machines_add_ceph_vms
        ;;
        enqueue)
            mkdir -p ~/tmp/teuthology/log/
            mkdir -p ~/tmp/teuthology/archive/
            my_overrides > "${OVERRIDES}"
            tcmd teuthology-suite --suite "${SUITE}" "${SUITE_ARGS[@]}"  -m "${MTYPE}" --ceph "${BUILD_BRANCH}" --suite-branch "${SUITE_BRANCH}" -b "${BACKEND}" "${OVERRIDES}" |& tee x
        ;;
        start)
            keyzap
            tcmd teuthology-dispatcher --log-dir $HOME/tmp/teuthology/log --tube "${MTYPE}" -v --exit-on-empty-queue
        ;;
        rerun)
            test "${JOB_YAML}"
            tcmd teuthology --interactive-on-error "${JOB_YAML}"
        ;;
    esac
done
