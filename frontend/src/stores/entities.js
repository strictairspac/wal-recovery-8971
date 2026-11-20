import {logSetsAPI,crashCasesAPI,recoveriesAPI,samplePointsAPI,purgesAPI} from '../api/entities.js';
export const store={logs:[],cases:[],runs:[],points:[],purges:[],async refresh(){[this.logs,this.cases,this.runs,this.points,this.purges]=await Promise.all([logSetsAPI.list(),crashCasesAPI.list(),recoveriesAPI.list(),samplePointsAPI.list(),purgesAPI.list()]);}};
